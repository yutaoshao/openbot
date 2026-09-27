"""Source-aware retrieval of original speech and neighbouring event context."""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path

from src.core.logging import get_logger
from src.memory.personal_retrieval import bm25

logger = get_logger(__name__)


@dataclass(frozen=True)
class HistoryHit:
    source: str
    text: str
    timestamp: str
    score: float = 0
    role: str = "user"
    conversation_id: str = ""


class PersonalHistory:
    """User speech is evidence; adjacent assistant speech is explicitly labelled context."""

    def __init__(
        self, root: Path = Path("data/conversations"), db_path: Path = Path("data/openbot.db")
    ) -> None:
        self.root = root
        self.db_path = db_path
        self._signature: tuple = ()
        self._records: dict[str, HistoryHit] = {}
        self._aliases: dict[str, str] = {}

    def _refresh(self) -> None:
        files = sorted(self.root.glob("*/*/*.jsonl"))
        watched = [*files, self.db_path, self.db_path.with_name(self.db_path.name + "-wal")]
        signature = tuple(
            (str(path), path.stat().st_mtime_ns, path.stat().st_size)
            for path in watched
            if path.is_file()
        )
        if signature == self._signature:
            return
        records: dict[str, HistoryHit] = {}
        aliases: dict[str, str] = {}
        for path in files:
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    logger.warning("personal_history.invalid_json", path=str(path), line=number)
                    continue
                source = f"{path}:{number}"
                hit = self._hit(source, item)
                message_id = item.get("stored_message_id")
                if hit is None or (message_id and f"message:{message_id}" in aliases):
                    continue
                records[source] = hit
                if message_id:
                    aliases[f"message:{message_id}"] = source
        if self.db_path.is_file():
            self._read_database(records, aliases)
        self._records, self._aliases, self._signature = records, aliases, signature

    def _read_database(self, records: dict[str, HistoryHit], aliases: dict[str, str]) -> None:
        with sqlite3.connect(f"file:{self.db_path.resolve()}?mode=ro", uri=True) as conn:
            conn.row_factory = sqlite3.Row
            for row in conn.execute("SELECT * FROM messages ORDER BY timestamp, id"):
                item = dict(row)
                source = f"message:{item['id']}"
                if source in aliases:
                    key = aliases[source]
                    if self._hit(source, item) is None:
                        records.pop(key, None)
                        aliases.pop(source, None)
                        continue
                    records[key] = replace(
                        records[key], conversation_id=item.get("conversation_id", "")
                    )
                    continue
                hit = self._hit(source, item)
                if hit:
                    records[source] = hit

    @staticmethod
    def _hit(source: str, item: dict) -> HistoryHit | None:
        role, content = item.get("role"), item.get("content")
        if role not in {"user", "assistant"} or not isinstance(content, str) or not content.strip():
            return None
        metadata = item.get("metadata") or {}
        if isinstance(metadata, str):
            metadata = json.loads(metadata)
        if role == "assistant" and metadata.get("turn_failure"):
            return None
        return HistoryHit(
            source,
            content,
            str(item.get("ts") or item.get("timestamp", "")),
            role=role,
            conversation_id=str(item.get("conversation_id", "")),
        )

    def search(self, query: str, *, limit: int = 5) -> list[HistoryHit]:
        self._refresh()
        users = [record for record in self._records.values() if record.role == "user"]
        scores = bm25(query, [item.text for item in users])
        hits = [
            replace(item, score=score)
            for item, score in zip(users, scores, strict=True)
            if score > 0
        ]
        return sorted(hits, key=lambda hit: (-hit.score, _time(hit), hit.source))[:limit]

    def context(
        self, query: str, *, profile_content: str = "", conversation_ids: list[str] | None = None
    ) -> str:
        hits = self.search(query, limit=8)
        references = re.findall(r"来源：([^；\n）]+)", profile_content)
        selected = {hit.source for hit in hits}
        for reference in references:
            key = self._aliases.get(reference, reference)
            if key in self._records:
                selected.add(key)
        # Episodic summaries supply conversation IDs; rank actual user speech before use.
        for conversation_id in conversation_ids or []:
            users = [
                record
                for record in self._records.values()
                if record.conversation_id == conversation_id and record.role == "user"
            ]
            ranked = sorted(
                zip(bm25(query, [item.text for item in users]), users, strict=True),
                key=lambda pair: -pair[0],
            )
            selected.update(item.source for score, item in ranked[:4] if score > 0)
        self._include_later_event_records(profile_content, selected)
        expanded = self._neighbours(selected)
        if not expanded:
            return ""
        logger.info("personal_history.lookup", sources=[hit.source for hit in expanded])
        return "\n".join(
            f"- {'用户原话' if hit.role == 'user' else '助手原话（仅语境，不代表用户决定）'}"
            f"（{hit.timestamp}；来源：{hit.source}）：{hit.text}"
            for hit in expanded
        )

    def _include_later_event_records(self, profile_content: str, selected: set[str]) -> None:
        names = set(re.findall(r"事件名称：([^；\n]+)", profile_content))
        for name in names:
            hits = self.search(name, limit=12)
            # Include recent matching speech as well as nearest semantic matches.
            selected.update(hit.source for hit in sorted(hits, key=_time)[-4:])

    def _neighbours(self, selected: set[str]) -> list[HistoryHit]:
        grouped: dict[str, list[HistoryHit]] = {}
        for record in self._records.values():
            # Never cross conversations; unlinked archive lines use their daily file.
            group = record.conversation_id or record.source.rsplit(":", 1)[0]
            grouped.setdefault(group, []).append(record)
        expanded = {key: self._records[key] for key in selected}
        for records in grouped.values():
            records.sort(key=lambda hit: (_time(hit), hit.source))
            for index, record in enumerate(records):
                if record.source in selected:
                    for adjacent in records[max(0, index - 2) : index + 4]:
                        expanded[adjacent.source] = adjacent
        return sorted(expanded.values(), key=lambda hit: (_time(hit), hit.source))


def _time(hit: HistoryHit) -> float:
    try:
        value = datetime.fromisoformat(hit.timestamp)
        return (value if value.tzinfo else value.replace(tzinfo=UTC)).timestamp()
    except ValueError:
        return 0
