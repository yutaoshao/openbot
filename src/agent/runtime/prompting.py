"""Prompt and turn-preparation helpers for the Agent runtime."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from src.agent.prompts import build_prompt_fragments
from src.core.user_scope import SINGLE_USER_ID

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


def resolve_route_tool_names(
    agent: Any,
    input_text: str,
    *,
    task_state: Any = None,
) -> tuple[str, ...]:
    """Return tools that indicate user-requested extra capability."""
    if not agent.tool_registry:
        return ()
    names = set(agent.tool_registry.match_deferred(input_text))
    if task_state is not None:
        names.update(task_state.activated_tools)
    return tuple(sorted(names))
