"""Human-readable stop verification failure messages."""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.agent.state.task_contract import ACTION_FILE_WRITE, TaskRequirement
from src.agent.state.task_contract_resources import canonical_path_within_directory
from src.tools.file_mutation_receipt import FILE_MUTATION_ACTIONS

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
    if expected and observed and not all(path in observed for path in expected):
        return (
            "本轮未完成：用户要求保存/修改文件，但写入目标不匹配。"
            f"期望写入 {', '.join(expected)}；实际写入 {', '.join(observed)}。"
        )
    if (
        requirement.allowed_write_dirs
        and observed
        and not _covers_allowed_dirs(
            requirement.allowed_write_dirs,
            observed,
        )
    ):
        return (
            "本轮未完成：用户要求保存/修改文件，但写入目标不匹配。"
            f"期望写入目录 {', '.join(requirement.allowed_write_dirs)}；"
            f"实际写入 {', '.join(observed)}。"
        )
    if any(event.action in FILE_MUTATION_ACTIONS for event in events):
        return "本轮未完成：结构化文件修改的凭证或最终后置条件验证失败。"
    if any(event.action == "command.execute" for event in events):
        return (
            "本轮未完成：只执行了 Bash，command_executed 不能作为结构化文件修改凭证；"
            "任务未继续自动重试。"
        )
    return "本轮未完成：用户要求保存/修改文件，但没有结构化文件修改凭证。"


def _observed_write_targets(events: tuple[ToolEffect, ...]) -> tuple[str, ...]:
    targets: list[str] = []
    for event in events:
        if event.status != "completed":
            continue
        if event.action not in FILE_MUTATION_ACTIONS:
            continue
        if event.effect != EFFECT_FILE_WRITTEN:
            continue
        target = event.resource.canonical if event.resource else event.target
        if target:
            targets.append(target)
    return tuple(dict.fromkeys(targets))


def _covers_allowed_dirs(directories: tuple[str, ...], paths: tuple[str, ...]) -> bool:
    return all(
        any(canonical_path_within_directory(path, directory) for path in paths)
        for directory in directories
    )
