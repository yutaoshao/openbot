"""JSONL conversation journal storage."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, tzinfo
from pathlib import Path
from typing import Any

DEFAULT_CONVERSATION_JOURNAL_ROOT = Path("data/conversations")


@dataclass(frozen=True)
class ConversationJournalEntry:
    ts: datetime
    role: str
    content: str
    channel: str
    conversation_id: str
    message_id: str
    stored_message_id: str = ""
    user_id: str = ""
    platform_user_id: str = ""
    model: str = ""
    trace_id: str = ""
    tokens_in: int | None = None
    tokens_out: int | None = None
    latency_ms: int | None = None
    tool_calls: list[dict[str, Any]] | None = None


class ConversationJournal:
    """Append conversation messages to local-date JSONL files."""

    def __init__(
        self,
        *,
        root: Path = DEFAULT_CONVERSATION_JOURNAL_ROOT,
        local_tz: tzinfo | None = None,
    ) -> None:
        self._root = root
        self._local_tz = local_tz

    def append(self, entry: ConversationJournalEntry) -> Path:
        local_ts = _localize(entry.ts, self._local_tz)
        target = self._path_for(local_ts)
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = _payload(entry, local_ts)
        with target.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False))
            handle.write("\n")
        return target

    def _path_for(self, ts: datetime) -> Path:
        return self._root / f"{ts:%Y}" / f"{ts:%m}" / f"{ts:%d}.jsonl"


def _payload(entry: ConversationJournalEntry, local_ts: datetime) -> dict[str, Any]:
    payload = asdict(entry)
    payload["ts"] = local_ts.isoformat()
    return {
        key: _jsonable(value)
        for key, value in payload.items()
        if value not in ("", None, [])
    }


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(item) for item in value]
    if value is None or isinstance(value, str | int | float | bool):
        return value
    return str(value)


def _localize(value: datetime, local_tz: tzinfo | None) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("conversation journal timestamp must be timezone-aware")
    return value.astimezone(local_tz or _local_timezone())


def _local_timezone() -> tzinfo:
    return datetime.now().astimezone().tzinfo or UTC
