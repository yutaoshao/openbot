"""Resumable, source-audited first pass over archived personal conversations."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections import Counter
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from src.memory.personal_events import event_identity, events_from_document, metadata, sections
from src.memory.personal_history import PersonalHistory
from src.memory.structured_json import parse_json_array_response

if TYPE_CHECKING:
    from pathlib import Path

    from src.memory.personal_profile import PersonalProfile

_PROMPT = """你逐条审阅用户历史原话，建立可追溯的个人档案候选。返回 JSON 数组，输入每条消息
必须恰好有一项：{message_id, claims:[...]}；无个人新信息 claims=[]。只能根据本条用户原话
提取，assistant 和相邻消息只用于解释指代。不要把询问当决定、计划当完成、建议当选择。
优先保留个人事实、身体、宠物、关系、稳定偏好，以及个人项目经历的起因/决定/理由/行动/结果。
短暂的软件调试、功能测试、工具使用、模型响应速度反馈、泛泛“我修改了代码”均为日常请求，
除非用户明确将其作为重要的个人项目决定或长期状态，否则 claims=[]。
当前一次性回答风格指令不是稳定偏好，普通问题不提取为用户事实。
重复已确认事实无须提取。不能确认归属时用 uncertain，不能猜测。每条 claim 包含
topic(个人/宠物/健康/关系/项目), subject, kind(confirmed/event/inference/uncertain),
fact, evidence(当前用户原话中的连续原文片段), event_time(不确定则空), status
(discussed/planned/ongoing/done/cancelled/unknown)。事实请填写 fact_key；偏好填写
preference_key、scope(通用/场景)、triggers；明确更正才填写 correction=true，沿用原有键。
旧记录没有稳定键但字段名称不同且明确为同一属性时，填 replaces_key=旧事实键。
重要经历填写 event_name、stage(origin/discussion/decision/rationale/action/outcome)，
已存在事件必须复用事件目录的 event_id；同批后续如可确认关联则复用事件名称。
仅明确计划或正在经历、后续未知的事件填写 followup_field 和 followup_question。
不确定的后续用 uncertain，不能从咨询生成待跟进计划。生日保留原文精度。
evidence 必须是本次原话的准确片段，不得用旧摘要充当来源。禁止输出输入以外的 message_id。
主体名称直接使用既有档案名；用户本人使用输入中 canonical_self 指定的称呼，
不要另建“用户”“我”的档案。同一项目使用目录中的既有名称。
"""


@dataclass(frozen=True)
class HistoricalTurn:
    message_id: str
    conversation_id: str
    source: str
    aliases: tuple[str, ...]
    timestamp: str
    user: str
    adjacent: tuple[dict[str, str], ...]
    closed: bool = False


def inventory(db_path: Path, archive_root: Path) -> tuple[list[HistoricalTurn], dict]:
    history = PersonalHistory(archive_root, db_path)
    history._refresh()
    with sqlite3.connect(f"file:{db_path.resolve()}?mode=ro", uri=True) as conn:
        conn.row_factory = sqlite3.Row
        messages = [
            dict(row)
            for row in conn.execute(
                "SELECT id, conversation_id, role, content, timestamp FROM messages "
                "ORDER BY timestamp, created_at, id"
            )
        ]
    duplicates: list[str] = []
    seen: set[tuple[str, str, str, str]] = set()
    aliases = history._aliases
    previous: dict[str, list[dict[str, str]]] = {}
    turns: list[HistoricalTurn] = []
    pending: dict[str, int] = {}
    mismatched_sources: list[str] = []
    for message in messages:
        fingerprint = (
            message["conversation_id"],
            message["role"],
            message["timestamp"],
            message["content"],
        )
        if fingerprint in seen:
            duplicates.append(message["id"])
            continue
        seen.add(fingerprint)
        group = previous.setdefault(message["conversation_id"], [])
        source = f"message:{message['id']}"
        if message["role"] == "user":
            reference = aliases.get(source, source)
            if reference != source and history._records[reference].text != message["content"]:
                mismatched_sources.append(reference)
                reference = source
            turns.append(
                HistoricalTurn(
                    message["id"],
                    message["conversation_id"],
                    reference,
                    tuple(dict.fromkeys((source, reference))),
                    message["timestamp"],
                    message["content"],
                    tuple(group[-4:]),
                )
            )
            pending[message["conversation_id"]] = len(turns) - 1
        elif message["role"] == "assistant" and message["conversation_id"] in pending:
            index = pending.pop(message["conversation_id"])
            turns[index] = replace(turns[index], closed=True)
        group.append({"role": message["role"], "content": message["content"][:1200]})
    all_users = [hit for hit in history._records.values() if hit.role == "user"]
    archive_users = [hit for hit in all_users if hit.source.startswith(str(archive_root) + "/")]
    damaged: list[str] = []
    archive_rows = 0
    archive_files = sorted(archive_root.glob("*/*/*.jsonl"))
    for path in archive_files:
        with path.open(encoding="utf-8") as stream:
            for number, line in enumerate(stream, 1):
                try:
                    json.loads(line)
                    archive_rows += 1
                except json.JSONDecodeError:
                    damaged.append(f"{path}:{number}")
    missing = [
        hit.source
        for hit in archive_users
        if not hit.conversation_id and hit.source not in {turn.source for turn in turns}
    ]
    return turns, {
        "database_user_messages": len(turns),
        "archived_user_messages": len(archive_users),
        "closed_database_turns": sum(turn.closed for turn in turns),
        "user_messages_without_database_reply": [turn.source for turn in turns if not turn.closed],
        "database_only_user_messages": len(all_users) - len(archive_users),
        "duplicate_database_message_ids": duplicates,
        "archive_content_mismatches": mismatched_sources,
        "archive_files": len(archive_files),
        "archive_rows": archive_rows,
        "damaged_archive_lines": damaged,
        "linked_archive_messages": len(aliases),
        "unlinked_archive_users": missing,
        "unique_evidence_users": len(all_users),
    }


def _rows(conn: sqlite3.Connection) -> dict[str, dict]:
    conn.row_factory = sqlite3.Row
    return {
        row["message_id"]: dict(row)
        for row in conn.execute("SELECT * FROM personal_backfill_turns")
    }


def _known(profile: PersonalProfile, drafts: dict[str, dict], batch: list[HistoricalTurn]) -> dict:
    facts: list[dict] = []
    events: list[dict] = []
    for path in profile.documents():
        content, _ = profile.read_document(path)
        facts.extend(
            {
                "path": path,
                "fact": line[2:].split("；", 1)[0],
                "key": metadata(line, "偏好键") or metadata(line, "事实键"),
                "source": metadata(line, "来源"),
            }
            for heading, line in sections(content)
            if heading == "已确认事实"
        )
        events.extend(
            {
                "id": event.id,
                "name": event.name,
                "subject": event.subject,
                "path": path,
                "status": event.status,
                "records": event.records[-2:],
            }
            for event in events_from_document(path, content)
        )
    profile_fact_count = len(facts)
    batch_text = "\n".join(turn.user for turn in batch)
    recent_drafts = list(drafts.values())[-80:]
    for row in recent_drafts:
        if row["status"] not in {"staged", "extracted"}:
            continue
        for claim in json.loads(row["claims"]):
            if claim.get("kind") == "confirmed":
                facts.append(
                    {
                        "path": claim.get("_document", ""),
                        "fact": claim["fact"],
                        "key": claim.get("preference_key") or claim.get("fact_key", ""),
                        "source": row.get("source", ""),
                    }
                )
            if claim.get("kind") != "event" or not claim.get("event_name"):
                continue
            path = claim.get("_document") or f"{claim['topic']}/{claim['subject']}.md"
            event_id = claim.get("event_id") or event_identity(path, claim["event_name"])
            if event_id not in {event["id"] for event in events}:
                events.append(
                    {
                        "id": event_id,
                        "name": claim["event_name"],
                        "subject": claim["subject"],
                        "path": path,
                        "status": claim.get("status", "unknown"),
                        "records": [claim["fact"]],
                    }
                )
    selected_events = [
        event for event in events if event["name"] in batch_text or event["subject"] in batch_text
    ]
    selected_events.extend(event for event in events[-35:] if event not in selected_events)
    return {
        "known_facts": [*facts[:profile_fact_count], *facts[profile_fact_count:][-80:]],
        "known_events": selected_events,
        "subjects": profile.documents(),
        "canonical_self": _aliases(profile).get("self_subject", ""),
    }


def _aliases(profile: PersonalProfile) -> dict:
    path = profile.root / "_migration" / "subject_aliases.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def _canonical_subject(claim: dict, profile: PersonalProfile) -> None:
    settings = _aliases(profile)
    subject = str(claim["subject"])
    if subject in settings.get("self_aliases", ()) and settings.get("self_subject"):
        claim["subject"] = settings["self_subject"]
    for rule in settings.get("rules", ()):
        if claim["topic"] != rule["topic"]:
            continue
        if rule.get("subjects") and claim["subject"] not in rule["subjects"]:
            continue
        if rule.get("subject_contains") and not any(
            marker in claim["subject"] for marker in rule["subject_contains"]
        ):
            continue
        if rule.get("contains") and not any(marker in claim["fact"] for marker in rule["contains"]):
            continue
        claim["topic"] = rule["target_topic"]
        claim["subject"] = rule["target_subject"]
        break


def _restrict_followup(claim: dict, turn: HistoricalTurn) -> None:
    """Only explicit plans and ongoing experiences can create follow-up candidates."""
    evidence = str(claim.get("evidence", ""))
    subject = str(claim.get("subject", ""))
    actor = "|".join(
        re.escape(value) for value in ("我们", "我", "她", "他", "它", subject) if value
    )
    personal_action = re.search(
        rf"(?:{actor}).{{0,16}}(?:计划|打算|准备|决定|正在|还在|开始|想|需要|"
        r"要(?:去|做|开始|接着|带|把|办|看|买|写|学))",
        evidence,
    )
    dated_action = re.search(
        r"(?:明天|接下来|下周|这周|等有时间).{0,12}(?:开始|执行|去|做|再来|看)", evidence
    )
    hypothetical = re.search(r"(?:如果|假如).{0,16}(?:想|要|计划)", evidence)
    if (
        claim.get("kind") != "event"
        or claim.get("status") not in {"planned", "ongoing"}
        or turn.user.lstrip().startswith("#")
        or not (personal_action or dated_action)
        or (hypothetical and not dated_action)
    ):
        claim.pop("followup_field", None)
        claim.pop("followup_question", None)


def _validate_batch(
    response: str, turns: list[HistoricalTurn], known_event_ids: set[str]
) -> dict[str, list[dict]]:
    parsed = parse_json_array_response(response)
    expected = {turn.message_id: turn for turn in turns}
    if not parsed.ok or len(parsed.items) != len(turns):
        raise ValueError(f"Incomplete historical extraction: {parsed.reason or 'wrong item count'}")
    output: dict[str, list[dict]] = {}
    for item in parsed.items:
        key = item.get("message_id")
        if key not in expected or key in output or not isinstance(item.get("claims"), list):
            raise ValueError("Historical extraction has duplicate/unknown ID or invalid claims")
        for claim in item["claims"]:
            if not isinstance(claim, dict) or not all(
                claim.get(field) for field in ("topic", "subject", "kind", "fact", "evidence")
            ):
                raise ValueError(f"Historical extraction has an invalid claim: {key}")
            if claim["kind"] not in {"confirmed", "event", "inference", "uncertain"}:
                raise ValueError(f"Historical extraction has an invalid kind: {key}")
            if claim["topic"] not in {"个人", "宠物", "健康", "关系", "项目"}:
                raise ValueError(f"Historical extraction has an invalid topic: {key}")
            if claim.get("event_id") and claim["event_id"] not in known_event_ids:
                raise ValueError(f"Historical extraction invented an event ID: {key}")
            if claim["evidence"].strip() not in expected[key].user:
                raise ValueError(f"Claim evidence is absent from original speech: {key}")
        output[key] = item["claims"]
    return output


async def stage_history(
    conn: sqlite3.Connection,
    turns: list[HistoricalTurn],
    profile: PersonalProfile,
    gateway: Any,
    *,
    batch_size: int = 8,
    limit: int | None = None,
) -> dict:
    known_rows = _rows(conn)
    pending = [
        turn
        for turn in turns
        if turn.message_id not in known_rows or known_rows[turn.message_id]["status"] == "failed"
    ]
    if limit is not None:
        pending = pending[:limit]
    for start in range(0, len(pending), batch_size):
        batch = pending[start : start + batch_size]
        await _stage_batch(conn, batch, profile, gateway, known_rows)
        print(f"Historical extraction: {start + len(batch)}/{len(pending)}", flush=True)
    return Counter(row["status"] for row in _rows(conn).values())


async def _stage_batch(
    conn: sqlite3.Connection,
    batch: list[HistoricalTurn],
    profile: PersonalProfile,
    gateway: Any,
    known_rows: dict[str, dict],
) -> None:
    payload = {
        "turns": [
            {
                "message_id": turn.message_id,
                "source": turn.source,
                "timestamp": turn.timestamp,
                "user": turn.user,
                "adjacent": turn.adjacent,
            }
            for turn in batch
        ],
        **_known(profile, known_rows, batch),
    }
    try:
        response = await gateway.chat(
            [
                {"role": "system", "content": _PROMPT},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ]
        )
        results = _validate_batch(
            response.text, batch, {item["id"] for item in payload["known_events"]}
        )
    except ValueError as exc:
        if len(batch) > 1:
            middle = len(batch) // 2
            await _stage_batch(conn, batch[:middle], profile, gateway, known_rows)
            await _stage_batch(conn, batch[middle:], profile, gateway, known_rows)
            return
        for turn in batch:
            _write_row(conn, turn, "failed", [], str(exc))
        conn.commit()
        print(f"Historical extraction failed for {batch[0].source}: {exc}", flush=True)
        return
    except Exception as exc:
        for turn in batch:
            _write_row(conn, turn, "failed", [], str(exc))
        conn.commit()
        print(f"Historical extraction request failed: {exc}", flush=True)
        return
    for turn in batch:
        claims = results[turn.message_id]
        try:
            for claim in claims:
                _canonical_subject(claim, profile)
                _restrict_followup(claim, turn)
                document = profile._claim_path(claim["topic"], claim["subject"])
                name = document.relative_to(profile.root).as_posix()
                claim["_document"] = name
                claim["_revision"] = (
                    profile.read_document(name)[1]
                    if document.exists()
                    else hashlib.sha256(b"").hexdigest()
                )
        except ValueError as exc:
            _write_row(conn, turn, "uncertain", claims, str(exc))
            known_rows[turn.message_id] = {
                "status": "uncertain",
                "source": turn.source,
                "claims": json.dumps(claims, ensure_ascii=False),
            }
            continue
        status = "staged" if claims else "none"
        _write_row(conn, turn, status, claims)
        known_rows[turn.message_id] = {
            "status": status,
            "source": turn.source,
            "claims": json.dumps(claims, ensure_ascii=False),
        }
    conn.commit()


def _write_row(
    conn: sqlite3.Connection, turn: HistoricalTurn, status: str, claims: list[dict], error: str = ""
) -> None:
    conn.execute(
        """
        INSERT INTO personal_backfill_turns
            (message_id, source, statement_at, source_aliases, status, claims, error, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(message_id) DO UPDATE SET status=excluded.status,
            claims=excluded.claims, error=excluded.error, updated_at=excluded.updated_at
    """,
        (
            turn.message_id,
            turn.source,
            turn.timestamp,
            json.dumps(turn.aliases, ensure_ascii=False),
            status,
            json.dumps(claims, ensure_ascii=False),
            error,
            datetime.now(UTC).isoformat(),
        ),
    )


def _resolve_event_reference(profile: PersonalProfile, claim: dict, name: str) -> None:
    """Reconcile a staged event ID against the authoritative Markdown catalog."""
    old_id = claim.get("event_id")
    if not old_id:
        return
    events = profile.events()
    original = next((event for event in events if event.id == old_id), None)
    if original and original.path == name:
        claim["event_name"] = original.name
        return
    matching = [
        event for event in events if event.path == name and event.name == claim.get("event_name")
    ]
    if len(matching) > 1 or (original and original.subject == claim.get("subject")):
        raise ValueError(f"Historical event reference is ambiguous: {name}")
    if len(matching) == 1:
        claim["event_id"] = matching[0].id
    elif claim.get("event_name"):
        claim["event_id"] = event_identity(name, claim["event_name"])
    else:
        raise ValueError(f"Historical event has no stable name: {name}")
    claim["_event_reconciliation"] = f"{old_id} -> {claim['event_id']}"


async def apply_history(
    conn: sqlite3.Connection, turns: list[HistoricalTurn], profile: PersonalProfile
) -> dict:
    rows = _rows(conn)
    written_revisions = dict(conn.execute("SELECT path, revision FROM personal_backfill_documents"))
    for turn in turns:
        row = rows.get(turn.message_id)
        if not row or row["status"] != "staged":
            continue
        claims = json.loads(row["claims"])
        try:
            for claim in claims:
                _canonical_subject(claim, profile)
                _restrict_followup(claim, turn)
                name = (
                    claim.get("_document")
                    or profile._claim_path(claim["topic"], claim["subject"])
                    .relative_to(profile.root)
                    .as_posix()
                )
                resolved = (
                    profile._claim_path(claim["topic"], claim["subject"])
                    .relative_to(profile.root)
                    .as_posix()
                )
                if name != resolved:
                    raise ValueError(f"Dossier selection changed since historical review: {name}")
                _resolve_event_reference(profile, claim, name)
                document = profile._document_path(name)
                content, actual = (
                    profile.read_document(name)
                    if document.exists()
                    else ("", hashlib.sha256(b"").hexdigest())
                )
                if "_revision" not in claim:
                    raise ValueError(f"Historical claim has no reviewed dossier revision: {name}")
                expected = written_revisions.get(name, claim["_revision"])
                if expected != actual:
                    already_applied = any(
                        line.startswith(f"- {claim['fact']}；") and f"；来源：{turn.source}" in line
                        for line in content.splitlines()
                    )
                    if not already_applied:
                        raise ValueError(f"Dossier changed since historical review: {name}")
                claim["_document"] = name
                claim["_revision"] = actual
                await profile.add_claim(claim, source=turn.source, stated_at=turn.timestamp)
                revision = profile.read_document(name)[1]
                conn.execute(
                    """
                    INSERT INTO personal_backfill_documents (path, revision) VALUES (?, ?)
                    ON CONFLICT(path) DO UPDATE SET revision=excluded.revision
                """,
                    (name, revision),
                )
                conn.commit()
                written_revisions[name] = revision
        except Exception as exc:
            _write_row(conn, turn, "failed", claims, str(exc))
            conn.commit()
            continue
        _write_row(
            conn,
            turn,
            "uncertain" if all(claim["kind"] == "uncertain" for claim in claims) else "extracted",
            claims,
        )
        conn.commit()
    return Counter(row["status"] for row in _rows(conn).values())


def review_report(conn: sqlite3.Connection, turns: list[HistoricalTurn], path: Path) -> None:
    rows = _rows(conn)
    uncertain_path = path.with_name("completeness-uncertain.jsonl")
    failed_path = path.with_name("completeness-failures.jsonl")
    with (
        path.open("w", encoding="utf-8") as output,
        uncertain_path.open("w", encoding="utf-8") as uncertain,
        failed_path.open("w", encoding="utf-8") as failures,
    ):
        for turn in turns:
            row = rows.get(turn.message_id)
            item = {
                "source": turn.source,
                "aliases": turn.aliases,
                "stated_at": turn.timestamp,
                "user": turn.user,
                "closed": turn.closed,
                "status": row["status"] if row else "unprocessed",
                "claims": json.loads(row["claims"]) if row else [],
                "error": row["error"] if row else "",
            }
            serialized = json.dumps(item, ensure_ascii=False) + "\n"
            output.write(serialized)
            if item["status"] in {"failed", "unprocessed"}:
                failures.write(serialized)
            if item["status"] == "uncertain" or any(
                claim["kind"] == "uncertain" for claim in item["claims"]
            ):
                uncertain.write(serialized)
