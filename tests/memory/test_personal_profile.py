from __future__ import annotations

import json
import sqlite3
import time
from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from src.agent.conversation.prompt_builder import PromptBuilder
from src.agent.runtime.turn_loop import TurnLoopExecution
from src.core.config import AgentConfig
from src.memory.personal_history import PersonalHistory
from src.memory.personal_profile import PersonalProfile
from src.memory.request_budget import (
    InputCount,
    compact_request_history,
    estimate_input_tokens,
    request_limit,
)


async def test_profile_correction_preserves_source_and_manual_edit_wins(tmp_path: Path) -> None:
    profile = PersonalProfile(tmp_path)
    first = {
        "topic": "宠物",
        "subject": "嘻嘻",
        "kind": "confirmed",
        "fact": "出生日期：2026-03-28 07:40",
    }
    assert await profile.add_claim(first, source="message:first", stated_at="2026-05-29")
    assert not await profile.add_claim(first, source="message:first", stated_at="2026-05-29")
    conflicting = {**first, "fact": "出生日期：2026-03-29 07:40"}
    await profile.add_claim(conflicting, source="message:unclear", stated_at="2026-06-01")
    document = tmp_path / "宠物" / "嘻嘻.md"
    assert "## 待核实信息\n- 出生日期：2026-03-29" in document.read_text()
    assert "## 已确认事实\n- 出生日期：2026-03-28" in document.read_text()
    corrected = {**conflicting, "correction": True}
    await profile.add_claim(corrected, source="message:correction", stated_at="2026-06-02")
    text, revision = profile.read_document("宠物/嘻嘻.md")
    assert "## 历史修订" in text and "来源：message:first" in text
    assert "## 已确认事实\n- 出生日期：2026-03-29" in text
    document.write_text(text.replace("2026-03-29 07:40", "2026-03-30 07:40"))
    with pytest.raises(RuntimeError, match="changed"):
        await profile.edit_document("宠物/嘻嘻.md", text, revision)
    assert "2026-03-30" in profile.context("嘻嘻几岁")
    assert "2026-03-30" in (tmp_path / "INDEX.md").read_text()


async def test_correction_uses_stable_key_across_wording(tmp_path: Path) -> None:
    profile = PersonalProfile(tmp_path)
    old = {
        "topic": "个人",
        "subject": "交流偏好",
        "kind": "confirmed",
        "fact": "回复偏好：不要使用 emoji",
        "preference_key": "emoji",
        "scope": "通用",
    }
    assert await profile.add_claim(old, source="message:old", stated_at="2026-06-01")
    new = {**old, "fact": "表情使用：现在可以使用 emoji", "correction": True}
    assert await profile.add_claim(new, source="message:new", stated_at="2026-07-01")
    document = (tmp_path / "个人" / "交流偏好.md").read_text()
    current = document.split("## 已确认事实", 1)[1].split("## 历史修订", 1)[0]
    assert "表情使用：现在可以使用 emoji" in current
    assert "回复偏好：不要使用 emoji" not in current
    assert "回复偏好：不要使用 emoji" in document.split("## 历史修订", 1)[1]
    assert "回复偏好：不要使用 emoji" not in profile.preference_context("打招呼")


async def test_aliases_from_later_sourced_claim_are_visible(tmp_path: Path) -> None:
    profile = PersonalProfile(tmp_path)
    base = {"topic": "宠物", "subject": "小橘", "kind": "confirmed", "fact": "物种：猫"}
    await profile.add_claim(base, source="message:old", stated_at="2026-06-01")
    await profile.add_claim(
        {**base, "fact": "性别：公", "aliases": ["阿橘"]},
        source="message:new",
        stated_at="2026-07-01",
    )
    assert "阿橘" in (tmp_path / "INDEX.md").read_text()
    assert "物种：猫" in profile.context("阿橘是什么")


async def test_age_annotation_ignores_superseded_birth_date(tmp_path: Path) -> None:
    profile = PersonalProfile(tmp_path)
    await profile.add_claim(
        {"topic": "宠物", "subject": "小白", "kind": "confirmed", "fact": "出生日期：2024-01-02"},
        source="message:old",
        stated_at="2026-05-01",
    )
    await profile.add_claim(
        {
            "topic": "宠物",
            "subject": "小白",
            "kind": "confirmed",
            "fact": "出生日期：未知",
            "correction": True,
        },
        source="message:new",
        stated_at="2026-06-01",
    )
    context = profile.context("小白多大了")
    assert "出生日期：未知" in context and "## 历史修订" in context
    assert "按 " not in context


async def test_history_uses_both_sources_and_stays_with_entity(tmp_path: Path) -> None:
    root = tmp_path / "conversations"
    day = root / "2026" / "09" / "17.jsonl"
    day.parent.mkdir(parents=True)
    day.write_text(
        "\n".join(
            json.dumps(item, ensure_ascii=False)
            for item in [
                {
                    "role": "user",
                    "content": "嘻嘻现在 2.9kg，算胖吗",
                    "ts": "2026-09-17",
                    "stored_message_id": "linked",
                },
                {"role": "assistant", "content": "猜测嘻嘻出生日期是 2025 年", "ts": "2026-09-17"},
            ]
        )
        + "\n"
    )
    db = tmp_path / "chats.db"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE messages (id TEXT, role TEXT, timestamp TEXT, content TEXT)")
        conn.executemany(
            "INSERT INTO messages VALUES (?, ?, ?, ?)",
            [
                ("linked", "user", "2026-09-17", "嘻嘻现在 2.9kg，算胖吗"),
                ("early", "user", "2026-04-24", "逗号是缅因和银渐层混血"),
            ],
        )
    history = PersonalHistory(root, db)
    assert len(history.search("嘻嘻2.9kg")) == 1
    assert history.search("逗号")[0].source == "message:early"
    context = history.context("嘻嘻体重多少", profile_content="# 嘻嘻\n")
    assert "2.9kg" in context and "助手原话（仅语境，不代表用户决定）" in context
    assert "逗号" not in context


async def test_related_weight_question_includes_birth_without_birthday_keyword(
    tmp_path: Path,
) -> None:
    profile = PersonalProfile(tmp_path / "profile")
    await profile.add_claim(
        {
            "topic": "宠物",
            "subject": "嘻嘻",
            "kind": "confirmed",
            "fact": "出生日期：2026-03-28 07:40",
        },
        source="data/conversations/2026/05/29.jsonl:40",
        stated_at="2026-05-29",
    )

    class NoPast:
        async def recall(self, query: str, user_id: str, *, limit: int) -> list:
            return []

        async def get_system_prompt_context(self, user_id: str, **kwargs) -> str:
            return ""

    class GeneralKnowledge:
        async def recall(self, query: str, user_id: str, *, limit: int) -> list[dict]:
            return [
                {
                    "category": "fact",
                    "content": "猫的体况评分可用于评估肥胖程度",
                    "memory_type": "general",
                },
                {
                    "category": "fact",
                    "content": "嘻嘻现在的体重是 3kg",
                    "memory_type": "personal_legacy",
                },
            ]

    prompt = PromptBuilder(GeneralKnowledge(), NoPast(), NoPast(), personal_profile=profile)
    context = await prompt.enrich("system", "嘻嘻现在 2.9kg 算胖吗", "local")
    assert "出生日期：2026-03-28 07:40" in context
    assert "data/conversations/2026/05/29.jsonl:40" in context
    assert "猫的体况评分" in context
    assert "现在的体重是 3kg" not in context


async def test_new_measurement_reuses_pet_dossier_even_if_extractor_changes_topic(
    tmp_path: Path,
) -> None:
    profile = PersonalProfile(tmp_path)
    await profile.add_claim(
        {"topic": "宠物", "subject": "测试猫", "kind": "confirmed", "fact": "出生日期：2025-02-01"},
        source="message:birth",
        stated_at="2025-03-01",
    )
    await profile.add_claim(
        {
            "topic": "体重",
            "subject": "测试猫",
            "kind": "confirmed",
            "fact": "体重：2025 年 6 月 3 日为 3.7kg",
        },
        source="message:weighing",
        stated_at="2025-06-04",
    )
    await profile.add_claim(
        {"topic": "宠物", "subject": "测试猫", "kind": "confirmed", "fact": "当天这只猫的体重两斤"},
        source="message:earlier",
        stated_at="2025-03-01",
    )
    await profile.add_claim(
        {
            "topic": "宠物",
            "subject": "测试猫",
            "kind": "confirmed",
            "fact": "截至2025年6月3日，小猫体重约3.7千克",
        },
        source="message:kilogram",
        stated_at="2025-06-05",
    )
    assert profile.documents() == ["宠物/测试猫.md"]
    document = (tmp_path / "宠物" / "测试猫.md").read_text()
    measurements = document.split("## 事件经过", 1)[1]
    assert "- 当天这只猫的体重两斤" in measurements
    assert "- 体重：" in measurements
    assert "小猫体重约3.7千克" in measurements


async def test_same_name_across_topics_requires_a_clear_subject(tmp_path: Path) -> None:
    for topic in ("宠物", "个人"):
        path = tmp_path / topic / "小白.md"
        path.parent.mkdir()
        path.write_text("# 小白\n别名：\n", encoding="utf-8")
    profile = PersonalProfile(tmp_path)
    claim = {"topic": "体重", "subject": "小白", "kind": "event", "fact": "体重：3kg"}
    with pytest.raises(ValueError, match="Ambiguous personal-memory subject"):
        await profile.add_claim(claim, source="message:unclear", stated_at="2026-09-27")
    assert await profile.add_claim(
        {**claim, "topic": "宠物"}, source="message:pet", stated_at="2026-09-27"
    )
    assert "体重：3kg" in (tmp_path / "宠物" / "小白.md").read_text()
    assert "体重：3kg" not in (tmp_path / "个人" / "小白.md").read_text()


async def test_failed_compression_keeps_tool_chain_and_original_messages() -> None:
    class EmptyGateway:
        async def chat(self, messages: list[dict]) -> SimpleNamespace:
            return SimpleNamespace(text="")

    messages = [
        {"role": "system", "content": "prompt"},
        {"role": "user", "content": "older"},
        {"role": "assistant", "content": "done"},
        {"role": "user", "content": "current"},
        {"role": "assistant", "tool_calls": [{"id": "a", "name": "lookup"}]},
        {"role": "tool", "tool_call_id": "a", "content": "result"},
    ]
    original = [item.copy() for item in messages]
    assert await compact_request_history(messages, EmptyGateway(), recent_budget=20)
    assert messages != original
    assert "模型历史摘要不可用" in messages[1]["content"]
    assert "older" in messages[1]["content"]
    assert "current" in messages[2]["content"]
    assert estimate_input_tokens(messages, [{"name": "lookup"}]).tokens > 0
    assert request_limit(272_000, 258_000, 16_384) == 241_616


async def test_preflight_compresses_at_ninety_percent_and_keeps_tool_chain() -> None:
    class Gateway:
        async def count_input(self, messages, tools, *, route_tier=None) -> InputCount:
            return InputCount(
                950 if any("older" in str(item.get("content", "")) for item in messages) else 200,
                exact=True,
                model_window=2000,
            )

        async def chat(self, messages) -> SimpleNamespace:
            return SimpleNamespace(text="summary retained")

    config = AgentConfig(input_token_budget=1000, recent_token_budget=400)
    agent = SimpleNamespace(model_gateway=Gateway(), config=config)
    messages = [
        {"role": "system", "content": "system prompt"},
        {"role": "user", "content": "[2026-05-29 09:00] older pet fact"},
        {"role": "assistant", "content": "old reply"},
        {"role": "user", "content": "current question"},
        {"role": "assistant", "tool_calls": [{"id": "a", "name": "lookup"}]},
        {"role": "tool", "tool_call_id": "a", "content": "current tool response"},
    ]
    context = SimpleNamespace(
        agent=agent, route_decision=None, clock=time.monotonic, messages=messages
    )
    execution = TurnLoopExecution(context)
    await execution._prepare_request_budget([{"name": "lookup"}])
    assert "data/conversations/2026/05/29.jsonl" in execution._messages[1]["content"]
    assert execution._messages[-3:] == [
        {"role": "user", "content": "current question"},
        {"role": "assistant", "tool_calls": [{"id": "a", "name": "lookup"}]},
        {"role": "tool", "tool_call_id": "a", "content": "current tool response"},
    ]
