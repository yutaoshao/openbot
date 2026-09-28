"""Source-aware retrieval of original speech and neighbouring event context."""

from __future__ import annotations

import json
import re
import threading
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path

from src.core.logging import get_logger
from src.infrastructure.storage.history_sources import HistorySources
from src.memory.personal_events import metadata
from src.memory.personal_retrieval import bm25
from src.memory.request_budget import estimate_input_tokens

logger = get_logger(__name__)
_HISTORY_CONTEXT_BUDGET = 24_000


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
        self._sources = HistorySources(root, db_path)
        self._lock = threading.RLock()
        self._signature: tuple = ()
        self._records: dict[str, HistoryHit] = {}
        self._aliases: dict[str, str] = {}

    def _refresh(self) -> None:
        signature, files = self._sources.signature()
        if signature == self._signature:
            return
        records: dict[str, HistoryHit] = {}
        aliases: dict[str, str] = {}
        for source, item in self._sources.archived(files):
            hit = self._hit(source, item)
            message_id = item.get("stored_message_id")
            if hit is None or (message_id and f"message:{message_id}" in aliases):
                continue
            records[source] = hit
            if message_id:
                aliases[f"message:{message_id}"] = source
        self._read_database(records, aliases)
        self._records, self._aliases, self._signature = records, aliases, signature

    def _read_database(self, records: dict[str, HistoryHit], aliases: dict[str, str]) -> None:
        for item in self._sources.messages():
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
        with self._lock:
            return self._search(query, limit=limit)

    def _search(self, query: str, *, limit: int) -> list[HistoryHit]:
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
        with self._lock:
            return self._context(
                query, profile_content=profile_content, conversation_ids=conversation_ids
            )

    def _context(
        self, query: str, *, profile_content: str, conversation_ids: list[str] | None
    ) -> str:
        hits = self.search(query, limit=8)
        selected = {hit.source for hit in hits}
        profile_sources = self._relevant_profile_sources(query, profile_content, selected)
        references = re.findall(r"来源：([^；\n）]+)", profile_sources)
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
        self._include_later_event_records(profile_sources, selected)
        expanded = self._neighbours(selected)
        if not expanded:
            return ""
        prioritized = list(
            dict.fromkeys(
                [
                    *(hit.source for hit in hits),
                    *(self._aliases.get(reference, reference) for reference in references),
                    *(
                        hit.source
                        for hit in sorted(expanded, key=_time, reverse=True)
                        if hit.source in selected
                    ),
                    *(hit.source for hit in expanded),
                ]
            )
        )
        by_source = {hit.source: hit for hit in expanded}
        chosen: list[HistoryHit] = []
        used = 0
        for source in prioritized:
            hit = by_source.get(source)
            if hit is None:
                continue
            cost = estimate_input_tokens([{"role": "user", "content": hit.text}]).tokens
            if chosen and used + cost > _HISTORY_CONTEXT_BUDGET:
                continue
            chosen.append(hit)
            used += cost
        chosen.sort(key=lambda hit: (_time(hit), hit.source))
        omitted = len(expanded) - len(chosen)
        logger.info(
            "personal_history.lookup",
            sources=[hit.source for hit in chosen],
            candidates=len(expanded),
            omitted=omitted,
            tokens_est=used,
        )
        if omitted:
            logger.info("personal_history.additional_sources_available", count=omitted)
        note = (
            f"另有 {omitted} 条相关或相邻历史未展开；仍可检索，不能据此断定没有后续。\n"
            if omitted
            else ""
        )
        return note + "\n".join(
            f"- {'用户原话' if hit.role == 'user' else '助手原话（仅语境，不代表用户决定）'}"
            f"（{hit.timestamp}；来源：{hit.source}）：{hit.text}"
            for hit in chosen
        )

    def _relevant_profile_sources(
        self, query: str, profile_content: str, already_selected: set[str]
    ) -> str:
        lines = [line for line in profile_content.splitlines() if "来源：" in line]
        if len(lines) <= 12:
            return "\n".join(lines)
        scores = bm25(query, lines)
        ranked = sorted(
            enumerate(lines),
            key=lambda pair: (
                any(
                    self._aliases.get(reference, reference) in already_selected
                    for reference in re.findall(r"来源：([^；\n）]+)", pair[1])
                ),
                scores[pair[0]],
            ),
            reverse=True,
        )
        relevant = [
            line
            for index, line in ranked
            if scores[index] > 0
            or any(
                self._aliases.get(reference, reference) in already_selected
                for reference in re.findall(r"来源：([^；\n）]+)", line)
            )
        ][:12]
        event_ids = {metadata(line, "事件ID") for line in relevant if metadata(line, "事件ID")}
        return "\n".join(
            dict.fromkeys(
                [
                    *relevant,
                    *(line for line in lines if metadata(line, "事件ID") in event_ids),
                ]
            )
        )

    def _include_later_event_records(self, profile_content: str, selected: set[str]) -> None:
        names = set(re.findall(r"事件名称：([^；\n]+)", profile_content))
        for name in names:
            hits = self.search(name, limit=12)
            # Include recent matching speech as well as nearest semantic matches.
            selected.update(hit.source for hit in sorted(hits, key=_time)[-4:])
        event_lines: dict[str, list[str]] = {}
        for line in profile_content.splitlines():
            event_id = metadata(line, "事件ID")
            if event_id:
                event_lines.setdefault(event_id, []).append(line)
        for lines in event_lines.values():
            sources = [
                self._aliases.get(metadata(line, "来源"), metadata(line, "来源")) for line in lines
            ]
            originals = [self._records[source] for source in sources if source in self._records]
            if not originals:
                continue
            latest = max(originals, key=_time)
            if any(metadata(line, "状态") in {"done", "cancelled"} for line in lines):
                continue
            # Short follow-ups may omit the name entirely ("已经打完了"). Include
            # candidates as evidence, never promote them to confirmed outcomes.
            verbs = {
                verb
                for verb in ("打", "接种", "寄", "预约", "面试", "入职", "复诊", "搬")
                if verb in latest.text or any(verb in line for line in lines)
            }
            if not verbs:
                continue
            names = {metadata(line, "事件名称") for line in lines}
            later = [
                hit
                for hit in self._records.values()
                if hit.role == "user"
                and _time(hit) > _time(latest)
                and any(verb in hit.text for verb in verbs)
                and re.search(r"已经|做完|打完|完成|结束|取消|改期|没去|终于|后来", hit.text)
                and (
                    hit.conversation_id == latest.conversation_id
                    or any(
                        name and (name in hit.text or (len(name) >= 3 and name[:2] in hit.text))
                        for name in names
                    )
                )
            ]
            ordered = sorted(later, key=_time)
            possible = [*ordered[:2], *ordered[-2:]]
            selected.update(hit.source for hit in possible)
            if possible:
                logger.info(
                    "personal_history.possible_outcome",
                    event_name=metadata(lines[0], "事件名称"),
                    sources=[hit.source for hit in possible],
                )

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
