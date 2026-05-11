"""Stop-time verification for user-visible agent replies."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.agent.state.task_contract import TaskContract

STATUS_COMPLETED = "completed"
STATUS_ERROR = "error"
EFFECT_WRITTEN = "written"
EFFECT_NONE = "none"
_INTERNAL_PREFIX = "Objective:"
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
class ToolEvent:
    """Structured fact about one executed tool call."""

    name: str
    operation: str = ""
    path: str = ""
    status: str = STATUS_COMPLETED
    effect: str = "none"
    summary: str = ""


@dataclass(frozen=True)
class ToolLedger:
    """Immutable collection of tool execution facts."""

    events: tuple[ToolEvent, ...] = ()

    def has_confirmed_write(self, target_paths: tuple[str, ...] = ()) -> bool:
        writes = [
            event
            for event in self.events
            if event.status == STATUS_COMPLETED and event.effect == EFFECT_WRITTEN
        ]
        if not target_paths:
            return bool(writes)
        written_paths = {event.path for event in writes}
        return all(path in written_paths for path in target_paths)

    def has_problem_events(self) -> bool:
        return any(event.status != STATUS_COMPLETED for event in self.events)

    def problem_summaries(self) -> tuple[str, ...]:
        return tuple(
            event.summary or f"{event.name} {event.status}"
            for event in self.events
            if event.status != STATUS_COMPLETED
        )


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
    """Check that the reply exposes failures and satisfies required outcomes."""
    cleaned = " ".join(final_text.strip().split())
    if _is_vague(cleaned) or _is_internal_summary(cleaned):
        return StopDecision(False, "本轮未完成：模型调用工具后没有生成有效最终回复。")
    if contract.requires_file_write and not ledger.has_confirmed_write(contract.target_paths):
        return StopDecision(False, "本轮未完成：用户要求保存/修改文件，但未确认写入成功。")
    if ledger.has_problem_events() and not _mentions_problem(cleaned):
        return StopDecision(False, _tool_problem_message(ledger))
    return StopDecision(True)


def ledger_from_tool_calls(tool_calls: list[dict[str, Any]]) -> ToolLedger:
    """Build structured tool facts from runtime execution records."""
    return ToolLedger(tuple(_event_from_record(record) for record in tool_calls))


def _event_from_record(record: dict[str, Any]) -> ToolEvent:
    metadata = record.get("metadata")
    data = metadata if isinstance(metadata, dict) else {}
    is_error = bool(record.get("is_error"))
    return ToolEvent(
        name=str(record.get("name") or "unknown"),
        operation=str(data.get("operation") or ""),
        path=str(data.get("path") or ""),
        status=str(data.get("status") or (STATUS_ERROR if is_error else STATUS_COMPLETED)),
        effect=str(data.get("effect") or EFFECT_NONE),
        summary=str(record.get("result_preview") or ""),
    )


def _is_vague(text: str) -> bool:
    return text.lower() in _VAGUE_REPLIES


def _is_internal_summary(text: str) -> bool:
    return text.startswith(_INTERNAL_PREFIX) and ("Evidence:" in text or "Completed:" in text)


def _mentions_problem(text: str) -> bool:
    lowered = text.lower()
    markers = ("失败", "错误", "未完成", "无法", "报错", "error", "failed")
    return any(marker in lowered for marker in markers)


def _tool_problem_message(ledger: ToolLedger) -> str:
    lines = ["本轮未完成：工具调用出现问题，但最终回复没有说明失败原因。"]
    lines.extend(f"- {summary}" for summary in ledger.problem_summaries())
    return "\n".join(lines)
