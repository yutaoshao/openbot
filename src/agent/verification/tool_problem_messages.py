"""User-visible messages for unresolved tool problems."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.tools.effects import ToolEffect


def blocking_tool_problem_message(problem_events: tuple[ToolEffect, ...]) -> str:
    lines = ["本轮未完成：工具调用出现问题，但最终回复没有说明失败原因。"]
    lines.extend(f"- {tool_problem_summary(event)}" for event in problem_events)
    return "\n".join(lines)


def nonblocking_tool_problem_notice(
    final_text: str,
    problem_events: tuple[ToolEffect, ...],
) -> str:
    lines = [final_text.rstrip(), "", "另外，有工具调用失败，已保留给你确认："]
    lines.extend(f"- {tool_problem_summary(event)}" for event in problem_events)
    return "\n".join(line for line in lines if line)


def tool_problem_summary(event: ToolEffect) -> str:
    if event.summary:
        return event.summary
    name = event.name or event.action
    return f"{name} {event.status}"
