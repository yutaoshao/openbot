"""Verification helpers for agent final responses."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.agent.state import TaskState

_VAGUE_REPLIES = {
    "分析完成",
    "已完成",
    "completed",
    "done",
    "finished",
    "ok",
    "task completed",
    "好的",
}
_INCOMPLETE_REPLY_PREFIX = "本轮未完成：模型调用工具后没有生成有效最终回复。"
_INTERNAL_PREFIX = "Objective:"


def verify_final_response(
    content: str,
    *,
    tool_calls_made: list[dict[str, object]],
    task_state: TaskState | None,
) -> tuple[str, bool]:
    """Replace vague completions with an explicit incomplete-turn message."""
    cleaned = " ".join(content.strip().split())
    if not cleaned and task_state is not None:
        return _incomplete_response(tool_calls_made), True
    if not tool_calls_made or task_state is None:
        return content, False
    lowered = cleaned.lower()
    if lowered not in _VAGUE_REPLIES and not _is_internal_summary(cleaned):
        return content, False
    return _incomplete_response(tool_calls_made), True


def _incomplete_response(tool_calls_made: list[dict[str, object]]) -> str:
    lines = [_INCOMPLETE_REPLY_PREFIX]
    if tool_calls_made:
        lines.append("已执行工具：")
        lines.extend(_tool_call_lines(tool_calls_made))
    return "\n".join(lines)


def _tool_call_lines(tool_calls_made: list[dict[str, object]]) -> list[str]:
    lines = []
    for call in tool_calls_made:
        name = str(call.get("name") or "unknown")
        is_error = bool(call.get("is_error"))
        status = "失败" if is_error else "已调用"
        lines.append(f"- {name}: {status}")
    return lines


def _is_internal_summary(text: str) -> bool:
    return text.startswith(_INTERNAL_PREFIX) and ("Evidence:" in text or "Completed:" in text)
