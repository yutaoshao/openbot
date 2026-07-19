"""Conversation state and model-route selection for the streaming loop."""

from __future__ import annotations

from typing import Any

from src.infrastructure.model_routing import RouteRequest

from .prompting import resolve_route_tool_names


def current_task_state(agent: Any, conversation_id: str) -> Any:
    """Read the active task state when conversation memory is available."""
    if not agent.conversation_manager or not conversation_id:
        return None
    return agent.conversation_manager.get_task_state(conversation_id)


def choose_route(agent: Any, input_text: str, task_state: Any) -> Any:
    """Choose one model route for the full streaming run."""
    decide_route = getattr(agent.model_gateway, "decide_route", None)
    if not callable(decide_route):
        return None
    tool_names = resolve_route_tool_names(agent, input_text, task_state=task_state)
    return decide_route(RouteRequest(input_text=input_text, tool_names=tool_names))
