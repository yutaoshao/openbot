"""Human-readable stop verification failure messages."""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.agent.state.task_contract import ACTION_FILE_WRITE, TaskRequirement

if TYPE_CHECKING:
    from src.tools.effects import ToolEffect

EFFECT_FILE_WRITTEN = "file_written"


def missing_requirement_message(
    requirement: TaskRequirement,
    action_effects: dict[str, str],
    events: tuple[ToolEffect, ...],
) -> str:
    if requirement.action == ACTION_FILE_WRITE:
        return _file_write_message(requirement, events)
    if requirement.action in action_effects:
        return "本轮未完成：用户要求的任务操作没有确认成功。"
    return "本轮未完成：没有确认用户要求的操作成功。"


def _file_write_message(requirement: TaskRequirement, events: tuple[ToolEffect, ...]) -> str:
    ambiguous = tuple(resource for resource in requirement.resources if resource.ambiguity)
    if ambiguous:
        options = "、".join(ambiguous[0].ambiguity)
        return f"本轮未完成：文件目标不明确，可能是 {options}。"
    expected = tuple(requirement.target_paths)
    observed = _observed_write_targets(events)
    if expected and observed:
        return (
            "本轮未完成：用户要求保存/修改文件，但写入目标不匹配。"
            f"期望写入 {', '.join(expected)}；实际写入 {', '.join(observed)}。"
        )
    return "本轮未完成：用户要求保存/修改文件，但未确认写入成功。"


def _observed_write_targets(events: tuple[ToolEffect, ...]) -> tuple[str, ...]:
    targets: list[str] = []
    for event in events:
        if event.status != "completed":
            continue
        if event.action not in {ACTION_FILE_WRITE, "file.edit"}:
            continue
        if event.effect != EFFECT_FILE_WRITTEN:
            continue
        target = event.resource.canonical if event.resource else event.target
        if target:
            targets.append(target)
    return tuple(dict.fromkeys(targets))
