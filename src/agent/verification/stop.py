"""Stop-time verification for user-visible agent replies."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from src.agent.state.task_contract import (
    ACTION_FILE_WRITE,
    ACTION_SCHEDULE_CREATE,
    ACTION_SCHEDULE_DELETE,
    ACTION_SCHEDULE_LIST,
    ACTION_SCHEDULE_UPDATE,
    TaskRequirement,
)
from src.agent.verification.stop_messages import missing_requirement_message
from src.agent.verification.tool_problem_messages import (
    blocking_tool_problem_message,
    nonblocking_tool_problem_notice,
)
from src.agent.verification.tool_recovery import is_recovered_tool_problem
from src.tools.effects import (
    EFFECT_NONE,
    STATUS_COMPLETED,
    STATUS_ERROR,
    ToolEffect,
)

if TYPE_CHECKING:
    from src.agent.state.task_contract import TaskContract

EFFECT_FILE_WRITTEN = "file_written"
_ACTION_EFFECTS = {
    ACTION_SCHEDULE_CREATE: "schedule_created",
    ACTION_SCHEDULE_DELETE: "schedule_deleted",
    ACTION_SCHEDULE_LIST: "schedule_listed",
    ACTION_SCHEDULE_UPDATE: "schedule_updated",
}
_INTERNAL_PREFIX = "Objective:"
_CLAIM_WINDOW_CHARS = 12
_SCHEDULE_CLAIM_PATTERNS = {
    ACTION_SCHEDULE_CREATE: re.compile(
        rf"(已|已经).{{0,{_CLAIM_WINDOW_CHARS}}}(创建|新增|新建|添加).{{0,{_CLAIM_WINDOW_CHARS}}}"
        rf"(定时任务|schedule)|(定时任务|schedule).{{0,{_CLAIM_WINDOW_CHARS}}}"
        rf"(已|已经).{{0,{_CLAIM_WINDOW_CHARS}}}(创建|新增|新建|添加)",
        re.IGNORECASE,
    ),
    ACTION_SCHEDULE_DELETE: re.compile(
        rf"(已|已经).{{0,{_CLAIM_WINDOW_CHARS}}}(删除|移除|取消).{{0,{_CLAIM_WINDOW_CHARS}}}"
        rf"(定时任务|schedule)|(定时任务|schedule).{{0,{_CLAIM_WINDOW_CHARS}}}"
        rf"(已|已经).{{0,{_CLAIM_WINDOW_CHARS}}}(删除|移除|取消)",
        re.IGNORECASE,
    ),
    ACTION_SCHEDULE_LIST: re.compile(
        rf"(已|已经).{{0,{_CLAIM_WINDOW_CHARS}}}(列出|查看).{{0,{_CLAIM_WINDOW_CHARS}}}"
        rf"(定时任务|schedule)|(定时任务|schedule).{{0,{_CLAIM_WINDOW_CHARS}}}"
        rf"(已|已经).{{0,{_CLAIM_WINDOW_CHARS}}}(列出|查看)",
        re.IGNORECASE,
    ),
    ACTION_SCHEDULE_UPDATE: re.compile(
        rf"(已|已经).{{0,{_CLAIM_WINDOW_CHARS}}}(更新|修改|改).{{0,{_CLAIM_WINDOW_CHARS}}}"
        rf"(定时任务|schedule)|(定时任务|schedule).{{0,{_CLAIM_WINDOW_CHARS}}}"
        rf"(已|已经).{{0,{_CLAIM_WINDOW_CHARS}}}(更新|修改|改)",
        re.IGNORECASE,
    ),
}
_VAGUE_REPLIES = {
    "",
    ".",
    "。",
    "?",
    "？",
    "done",
    "completed",
    "finished",
    "ok",
    "好的",
    "已完成",
    "分析完成",
}


@dataclass(frozen=True)
class ToolLedger:
    """Immutable collection of structured tool execution facts."""

    events: tuple[ToolEffect, ...] = ()

    def satisfies(self, requirement: TaskRequirement) -> bool:
        if requirement.action == ACTION_FILE_WRITE:
            return self._satisfies_file_write(requirement)
        expected_effect = _ACTION_EFFECTS.get(requirement.action)
        if expected_effect is None:
            return True
        return self._has_completed_effect(requirement, expected_effect)

    def has_completed_action(self, action: str) -> bool:
        expected_effect = _ACTION_EFFECTS.get(action)
        if expected_effect is None:
            return False
        return self._has_completed_effect(TaskRequirement(action), expected_effect)

    def has_problem_events(self) -> bool:
        return any(event.status != STATUS_COMPLETED for event in self.events)

    def has_completed_evidence(self) -> bool:
        return any(
            event.status == STATUS_COMPLETED and event.effect != EFFECT_NONE
            for event in self.events
        )

    def unresolved_problem_events(self) -> tuple[ToolEffect, ...]:
        unresolved: list[ToolEffect] = []
        for index, event in enumerate(self.events):
            if event.status == STATUS_COMPLETED:
                continue
            later_events = self.events[index + 1 :]
            if is_recovered_tool_problem(event, later_events):
                continue
            unresolved.append(event)
        return tuple(unresolved)

    def _satisfies_file_write(self, requirement: TaskRequirement) -> bool:
        if any(resource.error for resource in requirement.resources):
            return False
        writes = [
            event
            for event in self.events
            if event.status == STATUS_COMPLETED
            and event.action in {ACTION_FILE_WRITE, "file.edit"}
            and event.effect == EFFECT_FILE_WRITTEN
        ]
        if not requirement.target_paths and not requirement.allowed_write_dirs:
            return bool(writes)
        written_paths = {_event_target(event) for event in writes}
        if requirement.target_paths and not all(
            path in written_paths for path in requirement.target_paths
        ):
            return False
        return all(
            any(_path_inside_dir(_event_target(event), directory) for event in writes)
            for directory in requirement.allowed_write_dirs
        )

    def _has_completed_effect(self, requirement: TaskRequirement, effect: str) -> bool:
        for event in self.events:
            if event.status != STATUS_COMPLETED or event.action != requirement.action:
                continue
            if event.effect != effect:
                continue
            if requirement.target and event.target != requirement.target:
                continue
            return True
        return False


@dataclass(frozen=True)
class StopDecision:
    """Decision made immediately before surfacing a reply."""

    allow: bool
    message: str = ""


def verify_stop(
    contract: TaskContract,
    final_text: str,
    ledger: ToolLedger,
) -> StopDecision:
    """Check that the reply exposes failures and satisfies required actions."""
    cleaned = " ".join(final_text.strip().split())
    if _is_vague(cleaned) or _is_internal_summary(cleaned):
        return StopDecision(False, "本轮未完成：模型调用工具后没有生成有效最终回复。")
    for requirement in contract.required_actions:
        if not ledger.satisfies(requirement):
            return StopDecision(
                False,
                missing_requirement_message(requirement, _ACTION_EFFECTS, ledger.events),
            )
    for claimed_action in _claimed_schedule_actions(cleaned):
        if not ledger.has_completed_action(claimed_action):
            return StopDecision(
                False,
                missing_requirement_message(
                    TaskRequirement(claimed_action),
                    _ACTION_EFFECTS,
                    ledger.events,
                ),
            )
    unresolved_events = ledger.unresolved_problem_events()
    if unresolved_events and not _mentions_problem(cleaned):
        if ledger.has_completed_evidence() and not _has_required_operation_problem(
            unresolved_events
        ):
            return StopDecision(
                True,
                nonblocking_tool_problem_notice(final_text, unresolved_events),
            )
        return StopDecision(False, blocking_tool_problem_message(unresolved_events))
    return StopDecision(True)


def ledger_from_tool_calls(tool_calls: list[dict[str, Any]]) -> ToolLedger:
    """Build structured tool facts from runtime execution records."""
    events: list[ToolEffect] = []
    for record in tool_calls:
        effects = record.get("effects")
        if isinstance(effects, list):
            record_events = [
                _effect_from_record(item, record) for item in effects if isinstance(item, dict)
            ]
            events.extend(record_events)
            if record.get("is_error") and not record_events:
                events.append(_generic_error_effect(record))
        elif record.get("is_error"):
            events.append(_generic_error_effect(record))
    return ToolLedger(tuple(events))


def _effect_from_record(effect: dict[str, Any], record: dict[str, Any]) -> ToolEffect:
    parsed = ToolEffect.from_mapping(effect)
    if parsed.name and parsed.summary:
        return parsed
    return ToolEffect(
        action=parsed.action,
        status=parsed.status,
        effect=parsed.effect,
        target_type=parsed.target_type,
        target=parsed.target,
        details=parsed.details,
        name=parsed.name or str(record.get("name") or "unknown"),
        summary=parsed.summary or str(record.get("result_preview") or ""),
        resource=parsed.resource,
    )


def _generic_error_effect(record: dict[str, Any]) -> ToolEffect:
    return ToolEffect(
        action=str(record.get("name") or "tool"),
        status=STATUS_ERROR,
        effect=EFFECT_NONE,
        name=str(record.get("name") or "unknown"),
        summary=str(record.get("result_preview") or ""),
    )


def _is_vague(text: str) -> bool:
    return text.lower() in _VAGUE_REPLIES


def _is_internal_summary(text: str) -> bool:
    return text.startswith(_INTERNAL_PREFIX) and ("Evidence:" in text or "Completed:" in text)


def _claimed_schedule_actions(text: str) -> tuple[str, ...]:
    return tuple(
        action for action, pattern in _SCHEDULE_CLAIM_PATTERNS.items() if pattern.search(text)
    )


def _mentions_problem(text: str) -> bool:
    lowered = text.lower()
    markers = ("失败", "错误", "未完成", "无法", "报错", "error", "failed")
    return any(marker in lowered for marker in markers)


def _has_required_operation_problem(events: tuple[ToolEffect, ...]) -> bool:
    operation_actions = {ACTION_FILE_WRITE, "file.edit", *_ACTION_EFFECTS}
    return any(event.action in operation_actions for event in events)


def _path_inside_dir(path: str, directory: str) -> bool:
    normalized_path = path.strip().rstrip("/")
    normalized_dir = directory.strip().rstrip("/")
    if not normalized_path or not normalized_dir:
        return False
    return normalized_path.startswith(f"{normalized_dir}/")


def _event_target(event: ToolEffect) -> str:
    return event.resource.canonical if event.resource else event.target
