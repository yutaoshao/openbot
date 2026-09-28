"""Editable personal dossiers, their source records, and on-demand lookup."""

from __future__ import annotations

import asyncio
import hashlib
import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

from src.core.logging import get_logger
from src.memory.personal_documents import (
    HEADINGS,
    ProfileRevisionConflictError,
    _calendar_age,
    _document_aliases,
    _profile_lock,
    _single_line,
    _write_if_unchanged,
    append_claim,
)
from src.memory.personal_events import events_from_document, metadata, preference_lines, sections
from src.memory.personal_extraction import extract_claims

logger = get_logger(__name__)
_HEAD_TOPIC = frozenset({"个人", "宠物", "健康", "关系", "项目"})
_GENERIC = {"我的", "你的", "现在", "之前", "后来", "怎么", "什么", "为什么", "知道", "有没有"}


def _slug(text: str) -> str:
    safe = re.sub(r"[^\w-]+", "-", text.strip(), flags=re.UNICODE).strip("-_")
    return safe[:64] or "个人"


def _terms(text: str) -> set[str]:
    words = re.findall(r"[a-zA-Z][\w.-]{1,}|[\u3400-\u9fff]+", text.lower())
    tokens: set[str] = set()
    for word in words:
        if re.fullmatch(r"[\u3400-\u9fff]+", word):
            tokens.update(word[index : index + 2] for index in range(len(word) - 1))
        else:
            tokens.add(word)
    return tokens - _GENERIC


@dataclass(frozen=True)
class ProfileMatch:
    path: Path
    title: str
    content: str
    source: str
    score: int


class PersonalProfile:
    """Markdown is authoritative; all search views are rebuilt on read."""

    def __init__(self, root: Path = Path("data/personal_memory")) -> None:
        self.root = root.resolve()
        self._lock = asyncio.Lock()

    def _documents(self) -> list[Path]:
        if not self.root.exists():
            return []
        root = self.root.resolve()
        return sorted(
            path
            for path in self.root.rglob("*.md")
            if path.name != "INDEX.md" and path.is_file() and path.resolve().is_relative_to(root)
        )

    def documents(self) -> list[str]:
        return [path.relative_to(self.root).as_posix() for path in self._documents()]

    def read_document(self, name: str) -> tuple[str, str]:
        path = self._document_path(name)
        if not path.is_file():
            raise FileNotFoundError(name)
        content = path.read_text(encoding="utf-8")
        return content, hashlib.sha256(content.encode()).hexdigest()

    async def edit_document(self, name: str, content: str, revision: str) -> str:
        path = self._document_path(name)
        async with self._lock:
            with _profile_lock(self.root):
                current, actual = self.read_document(name)
                if actual != revision:
                    raise RuntimeError(f"Profile changed during edit: {name}")
                _write_if_unchanged(path, current, content)
                self._write_index()
        return hashlib.sha256(content.encode()).hexdigest()

    def _document_path(self, name: str) -> Path:
        path = (self.root / name).resolve()
        if not path.is_relative_to(self.root.resolve()) or path.name == "INDEX.md":
            raise ValueError("Invalid personal-memory document path")
        if path.suffix != ".md":
            raise ValueError("Personal-memory document must be Markdown")
        return path

    def matches(self, query: str, *, limit: int = 3) -> list[ProfileMatch]:
        query_terms = _terms(query)
        matches: list[ProfileMatch] = []
        if self.root.exists():
            with _profile_lock(self.root):
                self._write_index()
        for path in self._documents():
            content = path.read_text(encoding="utf-8")
            title = content.split("\n", 1)[0].lstrip("# ").strip() or path.stem
            aliases = re.search(r"^别名：[ \t]*(.*)$", content, flags=re.MULTILINE)
            names = [title, path.stem, *(aliases.group(1).split("、") if aliases else [])]
            lowered_query = query.lower()
            score = sum(
                10
                for name in names
                if name.strip()
                and (
                    name.strip().lower() in lowered_query
                    or (
                        "与" in name
                        and any(
                            len(part) > 1 and part.lower() in lowered_query
                            for part in name.split("与")
                        )
                    )
                )
            )
            score += len(query_terms & _terms(content))
            if score >= 8:
                matches.append(ProfileMatch(path, title, content, str(path), score))
        return sorted(matches, key=lambda item: (-item.score, str(item.path)))[:limit]

    def context(self, query: str, *, matches: list[ProfileMatch] | None = None) -> str:
        matches = self.matches(query) if matches is None else matches
        if not matches:
            return ""
        items = ["个人档案（Markdown 原文是权威来源；推测不得表述成已确认事实）："]
        for match in matches:
            confirmed = (
                match.content.split("## 已确认事实", 1)[1].split("\n## ", 1)[0]
                if "## 已确认事实" in match.content
                else ""
            )
            birth = re.search(r"^- 出生日期：(\d{4}-\d{2}-\d{2})", confirmed, re.MULTILINE)
            age = ""
            if birth:
                try:
                    today = datetime.now().astimezone().date()
                    calculated = _calendar_age(date.fromisoformat(birth[1]), today)
                    age = f"\n按 {today} 计算年龄：{calculated}。"
                except ValueError:
                    age = ""
            items.append(f"来源：{match.source}\n{match.content}{age}")
        items.append(
            "事件的未知后续不得推断为已完成。只有本次提供了允许追问的候选时，"
            "才可主动追问其后续；没有候选时不要自行追问历史事件进展。"
        )
        return "\n\n".join(items)

    def events(self):
        return [
            event
            for name in self.documents()
            for event in events_from_document(name, self.read_document(name)[0])
        ]

    def preference_context(self, query: str) -> str:
        entries = []
        for name in self.documents():
            content, revision = self.read_document(name)
            for line in preference_lines(content, query):
                entries.append(f"{line}（档案：{name}；版本：{revision}）")
        return "用户已确认的交流和行为偏好：\n" + "\n".join(entries) if entries else ""

    async def extract(
        self,
        gateway: Any,
        user_text: str,
        *,
        stated_at: str,
        context_messages: list[dict] | None = None,
    ) -> list[dict]:
        snapshots = {name: self.read_document(name) for name in self.documents()}
        catalog = [
            event
            for name, (content, _) in snapshots.items()
            for event in events_from_document(name, content)
        ]
        known_facts = [
            {
                "path": name,
                "fact": line[2:].split("；", 1)[0],
                "key": metadata(line, "偏好键")
                or metadata(line, "事实键")
                or line[2:].split("：", 1)[0],
                "source": metadata(line, "来源"),
            }
            for name, (content, _) in snapshots.items()
            for heading, line in sections(content)
            if heading == "已确认事实"
        ]
        claims = await extract_claims(
            gateway,
            {
                "current_user": user_text,
                "stated_at": stated_at,
                "adjacent_messages": context_messages or [],
                "known_events": [
                    {
                        "id": event.id,
                        "name": event.name,
                        "subject": event.subject,
                        "status": event.status,
                        "path": event.path,
                        "records": list(event.records[-3:]),
                    }
                    for event in catalog
                ],
                "subjects": [
                    {"path": name, "description": content.split("\n\n", 1)[0]}
                    for name, (content, _) in snapshots.items()
                ],
                "known_facts": known_facts,
            },
        )
        for claim in claims:
            selected_event = next(
                (event for event in catalog if event.id == claim.get("event_id")), None
            )
            if claim.get("event_id") and selected_event is None:
                raise ValueError("Extracted event ID is not in the source catalog")
            if selected_event:
                name = selected_event.path
                claim["event_name"] = selected_event.name
            else:
                name = (
                    self._claim_path(claim["topic"], claim["subject"])
                    .relative_to(self.root)
                    .as_posix()
                )
            claim["_document"] = name
            claim["_revision"] = snapshots.get(name, ("", hashlib.sha256(b"").hexdigest()))[1]
        return claims

    async def observe(self, gateway: Any, user_text: str, *, source: str, stated_at: str) -> int:
        claims = await self.extract(gateway, user_text, stated_at=stated_at)
        return await self.apply_claims(claims, source=source, stated_at=stated_at)

    async def add_claim(self, item: dict[str, Any], *, source: str, stated_at: str) -> bool:
        if not all(item.get(key) for key in ("topic", "subject", "fact")):
            return False
        if item.get("kind") not in HEADINGS:
            return False
        return bool(await self.apply_claims([item], source=source, stated_at=stated_at))

    async def apply_claims(self, claims: list[dict], *, source: str, stated_at: str) -> int:
        stored = 0
        async with self._lock:
            with _profile_lock(self.root):
                groups: dict[Path, list[dict]] = {}
                for claim in claims:
                    path = (
                        self._document_path(claim["_document"])
                        if claim.get("_document")
                        else self._claim_path(claim["topic"], claim["subject"])
                    )
                    groups.setdefault(path, []).append(claim)
                for path, items in groups.items():
                    stored += self._apply_document(path, items, source=source, stated_at=stated_at)
                self._write_index()
        return stored

    def _apply_document(self, path: Path, items: list[dict], *, source: str, stated_at: str) -> int:
        if not path.resolve().is_relative_to(self.root.resolve()):
            raise ValueError("Profile path leaves the personal-memory directory")
        old = path.read_text(encoding="utf-8") if path.exists() else ""
        pending = [
            item
            for item in items
            if not any(
                line.startswith(f"- {_single_line(str(item['fact']))}；")
                and f"；来源：{source}" in line
                for line in old.splitlines()
            )
        ]
        if not pending:
            return 0
        revision = hashlib.sha256(old.encode()).hexdigest()
        if any(item.get("_revision", revision) != revision for item in pending):
            raise ProfileRevisionConflictError(f"Profile changed since extraction: {path}")
        first = items[0]
        aliases = first.get("aliases", [])
        aliases = aliases if isinstance(aliases, list) else []
        content = old or (
            f"# {_single_line(first['subject'])}\n别名："
            + "、".join(_single_line(str(alias)) for alias in aliases)
            + "\n"
        )
        if old and aliases:
            present = _document_aliases(path)
            additions = [_single_line(str(alias)) for alias in aliases]
            merged = list(dict.fromkeys([*present, *(alias for alias in additions if alias)]))
            if merged != present:
                if re.search(r"^别名：", content, re.MULTILINE):
                    content = re.sub(
                        r"^别名：.*$",
                        "别名：" + "、".join(merged),
                        content,
                        count=1,
                        flags=re.MULTILINE,
                    )
                else:
                    heading, separator, remainder = content.partition("\n")
                    content = heading + "\n别名：" + "、".join(merged) + separator + remainder
        for item in pending:
            content = append_claim(
                content,
                item,
                source=source,
                stated_at=stated_at,
                path=path.relative_to(self.root).as_posix(),
            )
        _write_if_unchanged(path, old, content)
        logger.info("personal_profile.updated", source=source, document=str(path))
        return len(pending)

    def _claim_path(self, topic: str, subject: str) -> Path:
        canonical = topic if topic in _HEAD_TOPIC else "个人"
        path = self.root / _slug(canonical) / f"{_slug(subject)}.md"
        if topic in _HEAD_TOPIC and path.exists():
            return path
        candidates = [
            candidate
            for candidate in self._documents()
            if candidate.stem == subject or subject in _document_aliases(candidate)
        ]
        matching = [candidate for candidate in candidates if candidate.parent.name == topic]
        if len(matching) == 1:
            return matching[0]
        if len(candidates) == 1:
            return candidates[0]
        if candidates:
            raise ValueError(f"Ambiguous personal-memory subject: {subject} ({topic})")
        return path

    def _write_index(self) -> None:
        entries = [
            "# 个人档案索引",
            "",
            "由主题档案生成。手动编辑主题文档后，下次读取直接使用新内容。",
            "",
        ]
        for path in self._documents():
            content = path.read_text(encoding="utf-8")
            title = content.split("\n", 1)[0].lstrip("# ").strip() or path.stem
            aliases = re.search(r"^别名：[ \t]*(.*)$", content, flags=re.MULTILINE)
            description = next(
                (
                    line[2:].split("；", 1)[0]
                    for line in content.splitlines()
                    if line.startswith("- ")
                ),
                "",
            )
            entries.append(
                f"- [{title}]({path.relative_to(self.root).as_posix()})"
                + (f"：别名 {aliases.group(1)}" if aliases and aliases.group(1) else "")
                + (f"；内容 {description[:90]}" if description else "")
            )
        index = self.root / "INDEX.md"
        old = index.read_text(encoding="utf-8") if index.exists() else ""
        _write_if_unchanged(index, old, "\n".join(entries) + "\n")
