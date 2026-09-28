"""Conversation state and model-route selection for the streaming loop."""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.infrastructure.model_routing import RouteRequest

from .prompting import resolve_route_tool_names

if TYPE_CHECKING:
    from src.agent.conversation import ConversationManager
    from src.agent.state import TaskState
    from src.infrastructure.model_gateway import ModelGateway
    from src.infrastructure.model_routing import RouteDecision
    from src.tools.registry import ToolRegistry


def current_task_state(
    conversations: ConversationManager | None, conversation_id: str
) -> TaskState | None:
    """Read the active task state when conversation memory is available."""
    if conversations is None or not conversation_id:
        return None
    return conversations.get_task_state(conversation_id)


def choose_route(
    gateway: ModelGateway,
    registry: ToolRegistry | None,
    input_text: str,
    task_state: TaskState | None,
) -> RouteDecision | None:
    """Choose one model route for the full streaming run."""
    decide_route = getattr(gateway, "decide_route", None)
    if not callable(decide_route):
        return None
    tool_names = resolve_route_tool_names(registry, input_text, task_state=task_state)
    return decide_route(RouteRequest(input_text=input_text, tool_names=tool_names))
