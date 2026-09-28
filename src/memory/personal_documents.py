"""Markdown format, revision checks and atomic dossier writes."""

from __future__ import annotations

import calendar
import fcntl
import hashlib
import os
import re
import tempfile
from contextlib import contextmanager
from datetime import date
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


def _document_aliases(path: Path) -> list[str]:
    alias_line = re.search(r"^别名：[ \t]*(.*)$", path.read_text(encoding="utf-8"), re.M)
    return [alias.strip() for alias in alias_line.group(1).split("、")] if alias_line else []


def _fact_key(item: dict, fact: str) -> str:
    return _single_line(str(item.get("preference_key") or item.get("fact_key") or (
        fact.split("：", 1)[0] if "：" in fact else ""
    )))


def _line_key(line: str) -> str:
    from src.memory.personal_events import metadata

    return (metadata(line, "偏好键") or metadata(line, "事实键")
            or (line[2:].split("：", 1)[0] if "：" in line else ""))


def _supersede_claim(content: str, keys: set[str], new_source: str) -> str:
    """Move prior values of the same stable property into the revision history."""
    heading = "## 已确认事实"
    start = content.index(heading)
    end = content.find("\n## ", start + len(heading))
    end = len(content) if end < 0 else end
    lines = content[start:end].splitlines()
    if not keys:
        return content
    old_lines = [
        line
        for line in lines
        if line.startswith("- ") and _line_key(line) in keys
        and f"来源：{new_source}" not in line
    ]
    if not old_lines:
        return content
    for line in old_lines:
        lines.remove(line)
    updated = content[:start] + "\n".join(lines) + content[end:]
    history = "## 历史修订"
    if history not in updated:
        updated += f"\n\n{history}\n"
    return updated.rstrip() + "\n" + "\n".join(old_lines) + "\n"


def _conflicts_with_confirmed(content: str, fact: str, key: str) -> bool:
    if not key or "## 已确认事实" not in content:
        return False
    section = content.split("## 已确认事实", 1)[1].split("\n## ", 1)[0]
    return any(
        line.startswith("- ") and _line_key(line) == key
        and not line.startswith(f"- {fact}；")
        for line in section.splitlines()
    )


def _single_line(value: str) -> str:
    return " ".join(value.splitlines()).strip().replace("；", "，")


class ProfileRevisionConflictError(RuntimeError):
    """A human or another writer changed a dossier after extraction."""


def _calendar_age(birth: date, today: date) -> str:
    if birth > today:
        return "出生日期晚于查询日期，无法计算"
    months = (today.year - birth.year) * 12 + today.month - birth.month
    if today.day < birth.day:
        months -= 1
    year, month = divmod(birth.month - 1 + months, 12)
    anniversary = date(
        birth.year + year,
        month + 1,
        min(birth.day, calendar.monthrange(birth.year + year, month + 1)[1]),
    )
    return f"{months // 12} 岁 {months % 12} 个月 {(today - anniversary).days} 天"


@contextmanager
def _profile_lock(root: Path):
    root.mkdir(parents=True, exist_ok=True)
    with (root / ".write.lock").open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def _write_if_unchanged(path: Path, previous: str, updated: str) -> None:
    """Atomic replacement with optimistic protection against manual edits."""
    path.parent.mkdir(parents=True, exist_ok=True)
    before = hashlib.sha256(previous.encode()).digest()
    current = path.read_bytes() if path.exists() else b""
    if hashlib.sha256(current).digest() != before:
        raise ProfileRevisionConflictError(f"Profile changed during update: {path}")
    if previous == updated:
        return
    name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=path.parent, prefix=".profile-", delete=False
        ) as handle:
            name = handle.name
            handle.write(updated)
            handle.flush()
            os.fsync(handle.fileno())
        if (path.read_bytes() if path.exists() else b"") != current:
            raise ProfileRevisionConflictError(f"Profile changed during update: {path}")
        os.replace(name, path)
    finally:
        if name and os.path.exists(name):
            os.unlink(name)


HEADINGS = {
    "confirmed": "已确认事实",
    "event": "事件经过",
    "inference": "推测",
    "uncertain": "待核实信息",
}


def append_claim(content: str, item: dict, *, source: str, stated_at: str, path: str) -> str:
    """Apply a sourced claim; an explicit correction preserves the older value."""
    from src.memory.personal_events import event_identity

    fact = _single_line(str(item["fact"]))
    key = _fact_key(item, fact)
    kind = item["kind"]
    status = item.get("status", "unknown")
    if status not in {"discussed", "planned", "ongoing", "done", "cancelled", "unknown"}:
        raise ValueError(f"Invalid personal event status: {status}")
    if kind == "confirmed" and (
        fact.startswith("体重：")
        or re.search(r"体重.{0,24}(?:\d+(?:\.\d+)?|[一二三四五六七八九十两半]+)"
                     r"(?:斤|kg|公斤|千克|克)", fact, flags=re.IGNORECASE)
    ):
        kind = "event"
    basis = _single_line(str(item.get("basis") or ""))
    if kind == "inference" and not basis:
        kind = "uncertain"
    if (
        kind == "confirmed"
        and item.get("correction") is not True
        and _conflicts_with_confirmed(content, fact, key)
    ):
        kind = "uncertain"
    statement = (
        f"- {fact}；事件时间：{_single_line(str(item.get('event_time') or '未注明'))}；"
        f"陈述时间：{stated_at}；状态：{status}；来源：{source}"
    )
    if basis:
        statement += f"；依据：{basis}"
    if kind == "confirmed" and key:
        statement += f"；事实键：{key}"
    if kind == "uncertain":
        statement += "；需核实，不覆盖已确认事实"
    event_name = _single_line(str(item.get("event_name") or ""))
    if kind == "event" and event_name:
        event_id = item.get("event_id") or event_identity(path, event_name)
        stage = item.get("stage", "discussion")
        if stage not in {"origin", "discussion", "decision", "rationale", "action", "outcome"}:
            raise ValueError(f"Invalid event stage: {stage}")
        statement += f"；事件ID：{event_id}；事件名称：{event_name}；阶段：{stage}"
        question = _single_line(str(item.get("followup_question") or ""))
        field = _single_line(str(item.get("followup_field") or ""))
        if status in {"planned", "ongoing"} and question and field:
            statement += f"；待跟进：{field}；追问：{question}"
    scope = item.get("scope")
    if kind == "confirmed" and scope in {"通用", "场景"} and item.get("preference_key"):
        statement += (
            f"；偏好范围：{scope}；偏好键："
            f"{_single_line(str(item['preference_key']))}；适用场景："
            f"{_single_line(str(item.get('triggers') or ''))}"
        )
    heading = f"## {HEADINGS[kind]}"
    if heading not in content:
        content = content.rstrip() + f"\n\n{heading}\n"
    insert_at = content.index(heading) + len(heading)
    content = content[:insert_at] + f"\n{statement}" + content[insert_at:]
    if item.get("correction") is True and kind == "confirmed":
        old_key = _single_line(str(item.get("replaces_key") or ""))
        content = _supersede_claim(content, {value for value in (key, old_key) if value}, source)
    return content
