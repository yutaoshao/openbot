"""Prompt and turn-preparation helpers for the Agent runtime."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from src.agent.conversation.message_flow import UserMessageArchiveMetadata
from src.agent.prompts import build_prompt_fragments
from src.core.user_scope import SINGLE_USER_ID
from src.memory.message_format import render_llm_message

if TYPE_CHECKING:
    from src.agent.runtime.turn_request import TurnRequest

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

_CONTEXT_METADATA_GUIDANCE = (
    "Conversation context may contain internal message timestamp metadata in prefixes "
    "like [YYYY-MM-DD HH:MM]. Use those timestamps only to interpret chronology and "
    "relative dates. Do not copy or imitate timestamp prefixes in user-facing replies "
    "unless the user explicitly asks for them."
)


def build_system_prompt(
    agent: Any,
    *,
    input_text: str = "",
    task_state: Any = None,
) -> str:
    """Build the dynamic system prompt for the current turn."""
    template = agent.config.system_prompt or DEFAULT_SYSTEM_PROMPT
    prompt = template.format(date=datetime.now(UTC).strftime("%Y-%m-%d"))
    prompt += "\n\n" + _CONTEXT_METADATA_GUIDANCE

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
    request: TurnRequest,
) -> list[dict[str, Any]]:
    """Build model messages for the current turn."""
    if not agent.conversation_manager or not request.conversation_id:
        return _standalone_turn_messages(agent, request)
    return await _conversation_turn_messages(agent, request)


async def _conversation_turn_messages(
    agent: Any,
    request: TurnRequest,
) -> list[dict[str, Any]]:
    resolved_user_id = request.user_id or SINGLE_USER_ID
    await agent.conversation_manager.get_or_create_conversation(
        request.conversation_id,
        request.platform,
        resolved_user_id,
        agent.config.token_budget,
    )
    await agent.conversation_manager.add_user_message(
        request.conversation_id,
        request.input_text,
        timestamp=request.message_timestamp,
        archive_metadata=UserMessageArchiveMetadata(
            source_message_id=request.source_message_id,
            platform_user_id=request.platform_user_id,
            user_id=resolved_user_id,
        ),
    )
    task_state = agent.conversation_manager.get_task_state(request.conversation_id)
    return await agent.conversation_manager.build_messages(
        request.conversation_id,
        build_system_prompt(agent, input_text=request.input_text, task_state=task_state),
        request.input_text,
        resolved_user_id,
        message_timestamp=request.message_timestamp,
    )


def _standalone_turn_messages(
    agent: Any,
    request: TurnRequest,
) -> list[dict[str, Any]]:
    return [
        {
            "role": "system",
            "content": build_system_prompt(agent, input_text=request.input_text),
        },
        render_llm_message(
            {
                "role": "user",
                "content": request.input_text,
                "timestamp": request.message_timestamp,
            }
        ),
    ]


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
