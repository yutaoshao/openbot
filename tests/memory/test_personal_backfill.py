from __future__ import annotations

import json
import sqlite3
from types import SimpleNamespace
from typing import TYPE_CHECKING

from src.core.config import StorageConfig
from src.infrastructure.database import Database
from src.memory.personal_backfill import (
    HistoricalTurn,
    _canonical_subject,
    _resolve_event_reference,
    _restrict_followup,
    apply_history,
    review_report,
    stage_history,
)
from src.memory.personal_profile import PersonalProfile

if TYPE_CHECKING:
    from pathlib import Path


async def test_backfill_retries_failed_source_and_distinguishes_empty_result(tmp_path: Path):
    db_path = tmp_path / "history.db"
    database = Database(StorageConfig(db_path=str(db_path)))
    await database.initialize()
    await database.close()
    profile = PersonalProfile(tmp_path / "profile")
    turns = [
        HistoricalTurn(
            "first", "chat", "message:first", ("message:first",), "2026-06-01", "我喜欢收集邮票", ()
        ),
        HistoricalTurn(
            "second",
            "chat",
            "message:second",
            ("message:second",),
            "2026-06-02",
            "你能解释一下双指针吗",
            (),
        ),
    ]

    class BadGateway:
        async def chat(self, messages):
            ids = [item["message_id"] for item in json.loads(messages[1]["content"])["turns"]]
            return SimpleNamespace(
                text=json.dumps(
                    [
                        {
                            "message_id": key,
                            "claims": [
                                {
                                    "topic": "个人",
                                    "subject": "测试用户",
                                    "kind": "confirmed",
                                    "fact": "兴趣：集邮",
                                    "evidence": "编造的原话",
                                }
                            ],
                        }
                        for key in ids
                    ],
                    ensure_ascii=False,
                )
            )

    class GoodGateway:
        def __init__(self):
            self.calls = 0

        async def chat(self, messages):
            self.calls += 1
            ids = [item["message_id"] for item in json.loads(messages[1]["content"])["turns"]]
            return SimpleNamespace(
                text=json.dumps(
                    [
                        {
                            "message_id": key,
                            "claims": (
                                [
                                    {
                                        "topic": "个人",
                                        "subject": "测试用户",
                                        "kind": "confirmed",
                                        "fact": "兴趣：集邮",
                                        "evidence": "我喜欢收集邮票",
                                    }
                                ]
                                if key == "first"
                                else []
                            ),
                        }
                        for key in ids
                    ],
                    ensure_ascii=False,
                )
            )

    with sqlite3.connect(db_path) as conn:
        await stage_history(conn, turns, profile, BadGateway(), batch_size=2)
        assert dict(conn.execute("SELECT message_id, status FROM personal_backfill_turns")) == {
            "first": "failed",
            "second": "failed",
        }
        gateway = GoodGateway()
        await stage_history(conn, turns, profile, gateway, batch_size=2)
        assert dict(conn.execute("SELECT message_id, status FROM personal_backfill_turns")) == {
            "first": "staged",
            "second": "none",
        }
        await apply_history(conn, turns, profile)
        await apply_history(conn, turns, profile)
        assert gateway.calls == 1
        assert dict(conn.execute("SELECT message_id, status FROM personal_backfill_turns")) == {
            "first": "extracted",
            "second": "none",
        }
        document = (profile.root / "个人" / "测试用户.md").read_text()
        assert document.count("兴趣：集邮") == 1


async def test_backfill_does_not_overwrite_manual_edit_after_review(tmp_path: Path):
    db_path = tmp_path / "memory.db"
    database = Database(StorageConfig(db_path=str(db_path)))
    await database.initialize()
    await database.close()
    profile = PersonalProfile(tmp_path / "profile")
    await profile.add_claim(
        {"topic": "个人", "subject": "测试用户", "kind": "confirmed", "fact": "语言：中文"},
        source="message:old",
        stated_at="2026-06-01",
    )
    turn = HistoricalTurn(
        "change", "chat", "message:change", ("message:change",), "2026-07-01", "以后请用英文", ()
    )

    class Gateway:
        async def chat(self, messages):
            return SimpleNamespace(
                text=json.dumps(
                    [
                        {
                            "message_id": "change",
                            "claims": [
                                {
                                    "topic": "个人",
                                    "subject": "测试用户",
                                    "kind": "confirmed",
                                    "fact": "语言：英文",
                                    "fact_key": "语言",
                                    "correction": True,
                                    "evidence": "以后请用英文",
                                }
                            ],
                        }
                    ],
                    ensure_ascii=False,
                )
            )

    with sqlite3.connect(db_path) as conn:
        await stage_history(conn, [turn], profile, Gateway())
        dossier = tmp_path / "profile" / "个人" / "测试用户.md"
        dossier.write_text(dossier.read_text().replace("语言：中文", "语言：法文"))
        await apply_history(conn, [turn], profile)
        assert conn.execute("SELECT status FROM personal_backfill_turns").fetchone()[0] == "failed"
        assert "语言：法文" in dossier.read_text()
        assert "语言：英文" not in dossier.read_text()


async def test_ambiguous_subject_is_recorded_without_losing_other_turns(tmp_path: Path):
    db_path = tmp_path / "history.db"
    database = Database(StorageConfig(db_path=str(db_path)))
    await database.initialize()
    await database.close()
    profile = PersonalProfile(tmp_path / "profile")
    for topic in ("个人", "健康"):
        document = profile.root / topic / "测试用户.md"
        document.parent.mkdir(parents=True, exist_ok=True)
        document.write_text(f"# 测试用户\n别名：\n\n## 已确认事实\n- {topic}记录：已有\n")
    turns = [
        HistoricalTurn(
            "ambiguous", "chat", "message:ambiguous", (), "2026-06-02", "我养了一只猫", ()
        ),
        HistoricalTurn("valid", "chat", "message:valid", (), "2026-06-02", "我喜欢邮票", ()),
    ]

    class Gateway:
        async def chat(self, messages):
            return SimpleNamespace(
                text=json.dumps(
                    [
                        {
                            "message_id": "ambiguous",
                            "claims": [
                                {
                                    "topic": "宠物",
                                    "subject": "测试用户",
                                    "kind": "confirmed",
                                    "fact": "养猫：是",
                                    "evidence": "我养了一只猫",
                                }
                            ],
                        },
                        {
                            "message_id": "valid",
                            "claims": [
                                {
                                    "topic": "个人",
                                    "subject": "测试用户",
                                    "kind": "confirmed",
                                    "fact": "兴趣：邮票",
                                    "evidence": "我喜欢邮票",
                                }
                            ],
                        },
                    ],
                    ensure_ascii=False,
                )
            )

    with sqlite3.connect(db_path) as conn:
        await stage_history(conn, turns, profile, Gateway(), batch_size=2)
        assert dict(conn.execute("SELECT message_id,status FROM personal_backfill_turns")) == {
            "ambiguous": "uncertain",
            "valid": "staged",
        }
        await apply_history(conn, turns, profile)
        assert "兴趣：邮票" in (profile.root / "个人" / "测试用户.md").read_text()
        assert not (profile.root / "宠物" / "测试用户.md").exists()


def test_followup_requires_a_personal_plan_or_ongoing_experience():
    candidate = {
        "kind": "event",
        "status": "planned",
        "evidence": "你每天早上帮我检查所有代码",
        "followup_field": "结果",
        "followup_question": "后来呢？",
    }
    assistant_task = HistoricalTurn(
        "1", "chat", "message:1", (), "2026-06-01", "你每天早上帮我检查所有代码", ()
    )
    _restrict_followup(candidate, assistant_task)
    assert "followup_question" not in candidate
    personal_plan = {
        "kind": "event",
        "status": "planned",
        "evidence": "我明天要去外地出差",
        "followup_field": "结果",
        "followup_question": "出差后来怎么样了？",
    }
    planned_trip = HistoricalTurn(
        "2", "chat", "message:2", (), "2026-06-01", "我明天要去外地出差", ()
    )
    _restrict_followup(personal_plan, planned_trip)
    assert "followup_question" in personal_plan

    unrelated = {
        "kind": "event",
        "status": "ongoing",
        "evidence": "嘴角开裂了？",
        "followup_field": "结果",
        "followup_question": "后来呢？",
    }
    mixed_turn = HistoricalTurn(
        "3", "chat", "message:3", (), "2026-06-01", "我明天要去出差，嘴角开裂了？", ()
    )
    _restrict_followup(unrelated, mixed_turn)
    assert "followup_question" not in unrelated

    question = {
        "kind": "event",
        "status": "ongoing",
        "evidence": "小猫会对狗哈气，要怎么熟悉？",
        "subject": "小猫",
        "followup_field": "结果",
        "followup_question": "后来呢？",
    }
    _restrict_followup(
        question,
        HistoricalTurn("4", "chat", "message:4", (), "2026-06-01", question["evidence"], ()),
    )
    assert "followup_question" not in question


def test_local_subject_alias_rules_keep_personal_names_out_of_code(tmp_path: Path):
    profile = PersonalProfile(tmp_path / "profile")
    settings = profile.root / "_migration" / "subject_aliases.json"
    settings.parent.mkdir(parents=True)
    settings.write_text(
        json.dumps(
            {
                "self_subject": "测试用户",
                "self_aliases": ["用户"],
                "rules": [
                    {
                        "topic": "项目",
                        "subject_contains": ["某Agent"],
                        "target_topic": "项目",
                        "target_subject": "某Agent",
                    }
                ],
            },
            ensure_ascii=False,
        )
    )
    personal = {"topic": "个人", "subject": "用户", "fact": "兴趣：集邮"}
    project = {"topic": "项目", "subject": "用户开发的某Agent", "fact": "已经开始开发"}
    _canonical_subject(personal, profile)
    _canonical_subject(project, profile)
    assert personal["subject"] == "测试用户"
    assert project["subject"] == "某Agent"


async def test_backfill_reconciles_stale_event_id_and_separates_another_subject(tmp_path: Path):
    profile = PersonalProfile(tmp_path / "profile")
    await profile.add_claim(
        {
            "topic": "关系",
            "subject": "甲",
            "kind": "event",
            "event_name": "保险理赔",
            "fact": "甲开始理赔",
            "status": "ongoing",
        },
        source="message:first",
        stated_at="2026-06-01",
    )
    first = profile.events()[0]
    stale = {"kind": "event", "subject": "甲", "event_name": "保险理赔", "event_id": "evt-stale"}
    _resolve_event_reference(profile, stale, "关系/甲.md")
    assert stale["event_id"] == first.id
    other = {"kind": "event", "subject": "乙", "event_name": "保险理赔", "event_id": first.id}
    _resolve_event_reference(profile, other, "关系/乙.md")
    assert other["event_id"] != first.id
    assert other["_event_reconciliation"].startswith(first.id)


async def test_uncertain_historical_statement_is_not_promoted_to_fact(tmp_path: Path):
    db_path = tmp_path / "history.db"
    database = Database(StorageConfig(db_path=str(db_path)))
    await database.initialize()
    await database.close()
    profile = PersonalProfile(tmp_path / "profile")
    turn = HistoricalTurn(
        "unknown", "chat", "message:unknown", (), "2026-06-01", "我不记得第二针是不是打过了", ()
    )

    class Gateway:
        async def chat(self, messages):
            return SimpleNamespace(
                text=json.dumps(
                    [
                        {
                            "message_id": "unknown",
                            "claims": [
                                {
                                    "topic": "宠物",
                                    "subject": "测试猫",
                                    "kind": "uncertain",
                                    "fact": "第二针是否已接种未知",
                                    "evidence": "我不记得第二针是不是打过了",
                                }
                            ],
                        }
                    ],
                    ensure_ascii=False,
                )
            )

    with sqlite3.connect(db_path) as conn:
        await stage_history(conn, [turn], profile, Gateway())
        await apply_history(conn, [turn], profile)
        status = conn.execute("SELECT status FROM personal_backfill_turns").fetchone()[0]
        assert status == "uncertain"
        content = (profile.root / "宠物" / "测试猫.md").read_text()
        assert "## 待核实信息" in content and "第二针是否已接种未知" in content
        assert "## 已确认事实" not in content
        report = tmp_path / "review.jsonl"
        review_report(conn, [turn], report)
        assert "message:unknown" in report.with_name("completeness-uncertain.jsonl").read_text()
        assert report.with_name("completeness-failures.jsonl").read_text() == ""
