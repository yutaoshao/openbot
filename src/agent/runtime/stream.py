"""ReAct loop and prompt preparation helpers for the main Agent."""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from typing import Any

from src.agent.prompts import build_prompt_fragments
from src.agent.verification import verify_final_response
from src.core.logging import get_logger
from src.core.user_scope import SINGLE_USER_ID
from src.infrastructure.model_gateway import StreamChunk, Usage

from .finalize import finalize_agent_run
from .tool_executor import execute_tool_call, summarize_tool_result

logger = get_logger(__name__)

DEFAULT_SYSTEM_PROMPT = """You are OpenBot, a helpful personal AI assistant.

Current date: {date}

Guidelines:
- Be concise and accurate
- If you don't know something, say so honestly
- Respond in the same language as the user's message
- Use tools when they would help answer the question
- When the user asks you to do something on a schedule or repeatedly,
  use a scheduling tool if one is available
- Always explain what you found after using a tool
"""


def build_system_prompt(
    agent: Any,
    *,
    input_text: str = "",
    task_state: Any = None,
) -> str:
    """Build the dynamic system prompt for the current turn."""
    template = agent.config.system_prompt or DEFAULT_SYSTEM_PROMPT
    prompt = template.format(date=datetime.now(UTC).strftime("%Y-%m-%d"))

    fragments = build_prompt_fragments(input_text, task_state)
    if fragments:
        prompt += "\n\n" + "\n\n".join(fragments)

    if agent.skill_registry:
        skills_block = agent.skill_registry.get_metadata_prompt()
        if skills_block:
            prompt += "\n\n" + skills_block

    return prompt


async def prepare_agent_turn(
    agent: Any,
    input_text: str,
    conversation_id: str,
    platform: str,
    user_id: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]] | None]:
    """Build messages and tool schemas for the current turn."""
    resolved_user_id = user_id or SINGLE_USER_ID
    if agent.conversation_manager and conversation_id:
        await agent.conversation_manager.get_or_create_conversation(
            conversation_id,
            platform,
            resolved_user_id,
            agent.config.token_budget,
        )
        await agent.conversation_manager.add_user_message(conversation_id, input_text)
        task_state = agent.conversation_manager.get_task_state(conversation_id)
        messages = await agent.conversation_manager.build_messages(
            conversation_id,
            build_system_prompt(agent, input_text=input_text, task_state=task_state),
            input_text,
            resolved_user_id,
        )
    else:
        task_state = None
        messages = [
            {
                "role": "system",
                "content": build_system_prompt(agent, input_text=input_text, task_state=task_state),
            },
            {"role": "user", "content": input_text},
        ]

    tools = resolve_tools(agent, input_text, task_state=task_state)
    return messages, tools


def resolve_tools(
    agent: Any,
    input_text: str,
    *,
    task_state: Any = None,
) -> list[dict[str, Any]] | None:
    """Resolve core and activated deferred tools for the current turn."""
    if not agent.tool_registry:
        return None
    active_names = agent.tool_registry.get_default_active_names()
    active_names.update(agent.tool_registry.match_deferred(input_text))
    if task_state is not None:
        active_names.update(task_state.activated_tools)
    return agent.tool_registry.get_schemas(active_names=active_names)


async def run_stream_inner(
    agent: Any,
    input_text: str,
    conversation_id: str,
    platform: str,
    user_id: str,
    ctx: Any,
):
    """Inner streaming loop with trace context active."""
    messages, tools = await prepare_agent_turn(
        agent,
        input_text,
        conversation_id,
        platform,
        user_id,
    )

    await agent.event_bus.publish(
        "agent.think.start",
        {"conversation_id": conversation_id, "input_length": len(input_text)},
    )

    iterations = 0
    total_tokens_in = 0
    total_tokens_out = 0
    all_tool_calls: list[dict[str, Any]] = []
    final_text = ""
    final_model = ""
    task_start = time.monotonic()
    task_timeout = agent.config.task_timeout
    stuck_threshold = agent.config.stuck_detection_threshold
    recent_tool_sigs: list[str] = []

    while iterations < agent.max_iterations:
        if agent.conversation_manager and conversation_id:
            current_task_state = agent.conversation_manager.get_task_state(conversation_id)
        else:
            current_task_state = None
        tools = resolve_tools(agent, input_text, task_state=current_task_state)
        if task_timeout > 0:
            elapsed = time.monotonic() - task_start
            if elapsed >= task_timeout:
                final_text = (
                    f"Task exceeded time limit ({task_timeout}s). "
                    f"Completed {iterations} iterations."
                )
                logger.warning(
                    "task_failed",
                    surface="operational",
                    reason="task_timeout",
                    elapsed_s=int(elapsed),
                    iterations=iterations,
                )
                break

        iterations += 1
        ctx.iteration = iterations
        logger.info(
            "thought_step",
            surface="cognitive",
            iteration=iterations,
            max_iterations=agent.max_iterations,
        )

        accumulated_text = ""
        collected_tool_calls: list[Any] = []
        iter_usage: Usage | None = None

        async for chunk in agent.model_gateway.chat_stream(messages=messages, tools=tools):
            if chunk.type == "text":
                accumulated_text += chunk.text
                yield chunk
            elif chunk.type == "tool_call":
                collected_tool_calls.append(chunk.tool_call)
            elif chunk.type == "done":
                iter_usage = chunk.usage
                final_model = chunk.model

        if iter_usage:
            total_tokens_in += iter_usage.tokens_in
            total_tokens_out += iter_usage.tokens_out

        if not collected_tool_calls:
            logger.info(
                "decision_made",
                surface="cognitive",
                decision="final_reply",
                iteration=iterations,
            )
            final_text = accumulated_text
            break

        logger.info(
            "decision_made",
            surface="cognitive",
            decision="tool_calls",
            tool_count=len(collected_tool_calls),
            tools=[tool_call.name for tool_call in collected_tool_calls],
            iteration=iterations,
        )

        assistant_msg: dict[str, Any] = {"role": "assistant"}
        if accumulated_text:
            assistant_msg["content"] = accumulated_text
        assistant_msg["tool_calls"] = [
            {
                "id": tool_call.id,
                "type": "function",
                "function": {
                    "name": tool_call.name,
                    "arguments": json.dumps(tool_call.arguments, ensure_ascii=False),
                },
            }
            for tool_call in collected_tool_calls
        ]
        messages.append(assistant_msg)

        for tool_call in collected_tool_calls:
            yield StreamChunk(type="tool_status", tool_name=tool_call.name)

            tool_start = time.monotonic()
            tool_result = await execute_tool_call(
                agent,
                tool_call.name,
                tool_call.arguments,
                conversation_id=conversation_id,
                platform=platform,
                task_state=current_task_state,
                timeout_override=(
                    max(0.001, task_timeout - (time.monotonic() - task_start))
                    if task_timeout > 0
                    else None
                ),
            )
            tool_latency = int((time.monotonic() - tool_start) * 1000)
            activated_tools = tool_result.metadata.get("activated_tools") or []
            if agent.conversation_manager:
                agent.conversation_manager.record_tool_event(
                    conversation_id,
                    tool_call.name,
                    summarize_tool_result(tool_result.content),
                    is_error=tool_result.is_error,
                    activated_tools=(
                        activated_tools if isinstance(activated_tools, list) else None
                    ),
                )
                skill_name = tool_result.metadata.get("skill_name")
                if isinstance(skill_name, str) and skill_name:
                    agent.conversation_manager.protect_context(
                        conversation_id,
                        f"skill:{skill_name}",
                        tool_result.content[:4000],
                    )

            logger.info(
                "tool_called",
                surface="operational",
                tool=tool_call.name,
                status="error" if tool_result.is_error else "success",
                latency_ms=tool_latency,
                result_length=len(tool_result.content),
            )

            all_tool_calls.append(
                {
                    "name": tool_call.name,
                    "arguments": tool_call.arguments,
                    "result_preview": tool_result.content[:200],
                    "is_error": tool_result.is_error,
                }
            )

            messages.append(tool_result.to_message(tool_call.id))

            await agent.event_bus.publish(
                "agent.tool.executed",
                {
                    "conversation_id": conversation_id,
                    "tool": tool_call.name,
                    "is_error": tool_result.is_error,
                    "iteration": iterations,
                },
            )

        if stuck_threshold > 0:
            signature = "|".join(
                f"{tool_call.name}:{json.dumps(tool_call.arguments, sort_keys=True)}"
                for tool_call in collected_tool_calls
            )
            recent_tool_sigs.append(signature)
            if len(recent_tool_sigs) > stuck_threshold:
                recent_tool_sigs.pop(0)
            if len(recent_tool_sigs) >= stuck_threshold and len(set(recent_tool_sigs)) == 1:
                final_text = (
                    "Agent appears stuck — repeating the same tool calls. "
                    "Stopping to avoid wasting resources."
                )
                logger.warning(
                    "task_failed",
                    surface="operational",
                    reason="stuck_loop",
                    repeated_sig=signature[:200],
                    iterations=iterations,
                )
                break
    else:
        final_text = "Task exceeded maximum iterations."
        logger.warning(
            "task_failed",
            surface="operational",
            reason="max_iterations",
            iterations=iterations,
        )

    task_state = (
        agent.conversation_manager.get_task_state(conversation_id)
        if agent.conversation_manager and conversation_id
        else None
    )
    final_text, verified = verify_final_response(
        final_text,
        tool_calls_made=all_tool_calls,
        task_state=task_state,
    )
    if verified:
        await agent.event_bus.publish(
            "harness.completion_verified",
            {
                "conversation_id": conversation_id,
                "platform": platform,
                "iterations": iterations,
            },
        )

    await finalize_agent_run(
        agent,
        conversation_id=conversation_id,
        user_id=user_id,
        content=final_text,
        model=final_model,
        tokens_in=total_tokens_in,
        tokens_out=total_tokens_out,
        latency_ms=0,
        iterations=iterations,
        all_tool_calls=all_tool_calls,
    )

    yield StreamChunk(
        type="done",
        usage=Usage(tokens_in=total_tokens_in, tokens_out=total_tokens_out),
        model=final_model,
        iterations=iterations,
    )
