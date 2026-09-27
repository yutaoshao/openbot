"""Interpret editable event and preference records without a second fact store."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class PersonalEvent:
    id: str
    name: str
    subject: str
    path: str
    status: str
    records: tuple[str, ...]
    question: str
    field: str
    source: str

    @property
    def can_follow_up(self) -> bool:
        return self.status in {"planned", "ongoing"} and bool(self.question and self.field)


def metadata(line: str, key: str) -> str:
    match = re.search(rf"(?:^|；){re.escape(key)}：([^；\n]*)", line)
    return match[1].strip() if match else ""


def sections(content: str) -> list[tuple[str, str]]:
    heading = ""
    result = []
    for line in content.splitlines():
        if line.startswith("## "):
            heading = line[3:].strip()
        elif line.startswith("- "):
            result.append((heading, line))
    return result


def event_identity(path: str, name: str) -> str:
    return "evt-" + hashlib.sha256(f"{path}\n{name}".encode()).hexdigest()[:20]


def events_from_document(path: str, content: str) -> list[PersonalEvent]:
    subject = content.splitlines()[0].lstrip("# ") if content else path
    grouped: dict[str, list[str]] = {}
    for heading, line in sections(content):
        event_id = metadata(line, "事件ID")
        if heading == "事件经过" and event_id:
            grouped.setdefault(event_id, []).append(line)
    events = []
    for event_id, records in grouped.items():
        records.sort(key=_statement_time)
        state_records = [
            line
            for line in records
            if metadata(line, "状态") in {"planned", "ongoing", "done", "cancelled"}
            and metadata(line, "阶段") not in {"discussion", "rationale"}
        ]
        latest = state_records[-1] if state_records else records[-1]
        questions = [line for line in records if metadata(line, "追问")]
        question_record = questions[-1] if questions else ""
        events.append(
            PersonalEvent(
                id=event_id,
                name=metadata(latest, "事件名称"),
                subject=subject,
                path=path,
                status=metadata(latest, "状态") or "unknown",
                records=tuple(records),
                question=metadata(question_record, "追问"),
                field=metadata(question_record, "待跟进"),
                source=metadata(latest, "来源"),
            )
        )
    return events


def _statement_time(line: str) -> tuple[float, float, int]:
    def timestamp(key: str) -> float:
        try:
            return datetime.fromisoformat(metadata(line, key)).timestamp()
        except ValueError:
            return 0

    stages = ("origin", "discussion", "decision", "rationale", "action", "outcome")
    stage = metadata(line, "阶段")
    return (
        timestamp("陈述时间"),
        timestamp("事件时间"),
        stages.index(stage) if stage in stages else -1,
    )


def preference_lines(content: str, query: str) -> list[str]:
    from src.memory.personal_profile import _terms

    result = []
    for heading, line in sections(content):
        if heading != "已确认事实":
            continue
        scope = metadata(line, "偏好范围")
        triggers = metadata(line, "适用场景")
        if scope == "通用" or (scope == "场景" and _terms(triggers) & _terms(query)):
            result.append(line)
    return result
