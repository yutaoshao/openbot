"""Verification helpers for agent final responses."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.agent.state import TaskState

_VAGUE_REPLIES = {
    "分析完成",
    "completed",
    "done",
    "finished",
    "task completed",
}


def verify_final_response(
    content: str,
    *,
    tool_calls_made: list[dict[str, object]],
    task_state: TaskState | None,
) -> tuple[str, bool]:
    """Replace vague completions with a structured summary when needed."""
    cleaned = " ".join(content.strip().split())
    if not cleaned and task_state is not None:
        summary = task_state.completion_summary()
        if summary:
            return summary, True
        return content, False
    if not tool_calls_made or task_state is None:
        return content, False
    lowered = cleaned.lower()
    if lowered not in _VAGUE_REPLIES and len(cleaned) > 40:
        return content, False
    summary = task_state.completion_summary()
    if not summary:
        return content, False
    return summary, True
