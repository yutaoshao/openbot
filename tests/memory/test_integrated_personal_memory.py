from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.agent.conversation.prompt_builder import PromptBuilder
from src.core.config import StorageConfig
from src.infrastructure.database import Database
from src.infrastructure.embedding import NullEmbeddingService
from src.infrastructure.storage import Storage
from src.memory.personal_events import event_identity
from src.memory.personal_followups import PersonalFollowups
from src.memory.personal_history import PersonalHistory
from src.memory.personal_profile import PersonalProfile
from src.memory.personal_retrieval import PersonalRetrieval
from src.memory.personal_sync import PersonalMemorySync
from src.memory.procedural.service import ProceduralMemory
from src.memory.semantic.service import SemanticMemory


@pytest.fixture
async def memory(tmp_path):
    db = Database(StorageConfig(db_path=str(tmp_path / "memory.db")))
    await db.initialize()
    profile = PersonalProfile(tmp_path / "profiles")
    yield profile, Storage(db), db
    await db.close()


class EmptyRecall:
    async def recall(self, *args, **kwargs):
        return []


async def test_global_preferences_load_without_profile_keyword_and_manual_edit_wins(memory):
    profile, storage, _ = memory
    await profile.add_claim(
        dict(
            topic="个人",
            subject="交流偏好",
            kind="confirmed",
            fact="语言：中文",
            preference_key="language",
            scope="通用",
        ),
        source="message:language",
        stated_at="2026-09-01",
    )
    await profile.add_claim(
        dict(
            topic="个人",
            subject="交流偏好",
            kind="confirmed",
            fact="笔记：按章节保存",
            preference_key="notes",
            scope="场景",
            triggers="读书 笔记",
        ),
        source="message:notes",
        stated_at="2026-09-01",
    )
    procedural = ProceduralMemory(storage, None, profile=profile)
    builder = PromptBuilder(EmptyRecall(), EmptyRecall(), procedural, personal_profile=profile)
    unrelated = await builder.enrich("system", "什么是双指针", "local-single-user")
    assert "语言：中文" in unrelated
    assert "笔记：按章节保存" not in unrelated
    assert "笔记：按章节保存" in await procedural.get_system_prompt_context("u", query="读书笔记")
    path = profile.root / "个人/交流偏好.md"
    path.write_text(path.read_text().replace("语言：中文", "语言：英文"))
    assert "语言：英文" in await builder.enrich("system", "什么是双指针", "local-single-user")


class MeaningEmbedding:
    def __init__(self):
        self.batches = 0

    async def embed(self, text):
        return [1.0, 0.0] if any(word in text for word in ("赔付", "补偿", "事故")) else [0.0, 1.0]

    async def embed_batch(self, texts):
        self.batches += 1
        return [await self.embed(text) for text in texts]


class OrderingReranker:
    def __init__(self):
        self.called = False

    async def rerank_dicts(self, query, items, **kwargs):
        self.called = True
        return sorted(items, key=lambda item: "保险" not in item["content"])


async def test_paraphrase_retrieval_cache_rebuild_and_manual_edit_during_rerank(memory):
    profile, storage, _ = memory
    await profile.add_claim(
        dict(topic="关系", subject="某人", kind="event", fact="保险赔付的金额仍未确定"),
        source="message:a",
        stated_at="2026-07-01",
    )
    embedding, reranker = MeaningEmbedding(), OrderingReranker()
    retrieval = PersonalRetrieval(
        profile, index=storage.personal_index, embedding=embedding, reranker=reranker
    )
    results = await retrieval.recall("补偿的事情怎样了")
    assert any("保险赔付" in item.content for item in results)
    assert reranker.called
    calls = embedding.batches
    await retrieval.rebuild()
    assert embedding.batches == calls
    path = profile.root / "关系/某人.md"
    path.write_text(path.read_text().replace("仍未确定", "已收到"))
    results = await retrieval.recall("补偿的事情怎样了")
    assert "已收到" in results[0].content and "仍未确定" not in results[0].content
    assert embedding.batches > calls

    class EditingReranker(OrderingReranker):
        async def rerank_dicts(self, query, items, **kwargs):
            path.write_text("# 改名\n\n## 已确认事实\n- 已手动删除赔付记录\n")
            return items

    retrieval.reranker = EditingReranker()
    assert await retrieval.recall("补偿的事情怎样了") == []
    path.unlink()
    await retrieval.rebuild()
    assert await storage.personal_index.all() == []


async def test_reranked_dossier_can_displace_three_direct_matches(memory):
    profile, storage, _ = memory
    for name in ("甲", "乙", "丙"):
        await profile.add_claim(
            dict(topic="关系", subject=name, kind="confirmed", fact=f"事件：{name}提过赔付"),
            source=f"message:{name}",
            stated_at="2026-06-01",
        )
    await profile.add_claim(
        dict(topic="关系", subject="丁", kind="event", fact="保险赔付到账了"),
        source="message:result",
        stated_at="2026-07-01",
    )

    class PrioritiseResult:
        async def rerank_dicts(self, query, items, **kwargs):
            return sorted(items, key=lambda item: "到账了" not in item["content"])

    retrieval = PersonalRetrieval(
        profile,
        index=storage.personal_index,
        embedding=MeaningEmbedding(),
        reranker=PrioritiseResult(),
    )
    matches = await retrieval.recall("甲乙丙保险赔付后来怎样")
    assert len(matches) == 3
    assert any("到账了" in match.content for match in matches)


async def test_backfilled_profile_embeddings_are_batched(memory):
    profile, storage, _ = memory
    path = profile.root / "项目" / "研究.md"
    path.parent.mkdir(parents=True)
    path.write_text(
        "# 研究\n\n## 已确认事实\n"
        + "\n".join(f"- 阶段{i}：已记录；来源：message:{i}" for i in range(35))
    )

    class BoundedEmbedding(MeaningEmbedding):
        async def embed_batch(self, texts):
            assert len(texts) <= 32
            return await super().embed_batch(texts)

    embedding = BoundedEmbedding()
    retrieval = PersonalRetrieval(profile, index=storage.personal_index, embedding=embedding)
    chunks = await retrieval.rebuild()
    assert len(chunks) == 35
    assert embedding.batches == 2


async def test_direct_dossier_reranks_using_relevant_old_record(memory):
    profile, storage, _ = memory
    path = profile.root / "项目" / "研究.md"
    path.parent.mkdir(parents=True)
    path.write_text(
        "# 研究\n\n## 事件经过\n"
        + "\n".join(
            [
                *(f"- 最近阶段{i}：整理资料；来源：message:{i}" for i in range(60)),
                "- 保险赔付进度：尚未确定；来源：message:old",
            ]
        )
    )

    class ObserveCandidates:
        content = ""

        async def rerank_dicts(self, query, items, **kwargs):
            self.content = next(item["content"] for item in items if item["path"] == "项目/研究.md")
            return items

    reranker = ObserveCandidates()
    retrieval = PersonalRetrieval(
        profile, index=storage.personal_index, embedding=MeaningEmbedding(), reranker=reranker
    )
    assert await retrieval.recall("研究的保险赔付进度")
    assert "保险赔付进度：尚未确定" in reranker.content


async def test_event_progression_reuses_id_and_does_not_turn_consultation_into_plan(memory):
    profile, _, _ = memory
    base = dict(topic="宠物", subject="猫咪", kind="event", event_name="第二针疫苗")
    await profile.add_claim(
        dict(base, fact="咨询第二针安排", status="discussed", stage="discussion"),
        source="message:1",
        stated_at="2026-06-01",
    )
    assert not profile.events()[0].can_follow_up
    await profile.add_claim(
        dict(
            base,
            fact="决定周末接种",
            status="planned",
            stage="decision",
            followup_field="接种结果",
            followup_question="猫咪第二针打了吗？",
        ),
        source="message:2",
        stated_at="2026-06-02",
    )
    event = profile.events()[0]
    assert event.can_follow_up
    await profile.add_claim(
        dict(base, fact="已经接种", status="done", stage="outcome"),
        source="message:3",
        stated_at="2026-06-09",
    )
    assert len(profile.events()) == 1
    assert profile.events()[0].id == event.id
    assert not profile.events()[0].can_follow_up
    assert len(profile.events()[0].records) == 3


async def test_adjacent_assistant_suggestion_is_context_and_concurrent_edit_is_not_overwritten(
    memory,
):
    profile, _, _ = memory
    await profile.add_claim(
        dict(topic="个人", subject="交流偏好", kind="confirmed", fact="语言：中文"),
        source="message:1",
        stated_at="2026-06-01",
    )
    adjacent = [{"id": "before", "role": "assistant", "content": "是否改用英文？"}]

    class Gateway:
        async def chat(self, messages):
            payload = json.loads(messages[1]["content"])
            assert payload["adjacent_messages"] == adjacent
            path = profile.root / "个人/交流偏好.md"
            path.write_text(path.read_text().replace("中文", "法文"))
            return SimpleNamespace(
                text=json.dumps(
                    [
                        dict(
                            topic="个人",
                            subject="交流偏好",
                            kind="confirmed",
                            fact="语言：英文",
                            correction=True,
                        )
                    ],
                    ensure_ascii=False,
                )
            )

    claims = await profile.extract(
        Gateway(), "就这样吧", stated_at="2026-06-02", context_messages=adjacent
    )
    with pytest.raises(RuntimeError, match="changed since extraction"):
        await profile.apply_claims(claims, source="message:2", stated_at="2026-06-02")
    assert "语言：法文" in profile.read_document("个人/交流偏好.md")[0]


async def test_history_follows_event_sources_and_adjacent_outcome_across_dates(memory):
    profile, storage, db = memory
    await storage.conversations.create(id="chat", platform="web", user_id="local-single-user")
    from datetime import UTC, datetime, timedelta

    base = datetime(2026, 6, 1, tzinfo=UTC)
    for index, (role, content) in enumerate(
        [
            ("user", "猫咪的第二针准备周末去打"),
            ("assistant", "考虑到上次检查正常，可以按计划进行"),
            ("user", "好的，因为之前检查没问题，那就这样决定"),
            ("assistant", "好"),
            ("user", "已经打完了，没什么不适"),
        ]
    ):
        await storage.messages.add(
            id=f"event{index}",
            conversation_id="chat",
            role=role,
            content=content,
            timestamp=base + timedelta(days=index),
        )
    history = PersonalHistory(profile.root / "missing", Path(db.db_path))
    content = history.context(
        "当时为什么这样决定，后来呢", profile_content="来源：message:event2；事件名称：第二针疫苗"
    )
    assert "因为之前检查没问题" in content and "已经打完了" in content
    assert "助手原话（仅语境，不代表用户决定）" in content
    assert "message:event4" in content


async def test_cross_date_short_outcome_is_found_beyond_neighbour_window(memory):
    profile, storage, db = memory
    await storage.conversations.create(id="later", platform="web", user_id="local-single-user")
    from datetime import UTC, datetime, timedelta

    begin = datetime(2026, 6, 1, tzinfo=UTC)
    await storage.messages.add(
        id="plan",
        conversation_id="later",
        role="user",
        content="猫咪第二针准备周末去打",
        timestamp=begin,
    )
    for index in range(12):
        await storage.messages.add(
            id=f"other{index}",
            conversation_id="later",
            role="user",
            content=f"其它日常话题{index}",
            timestamp=begin + timedelta(days=1, minutes=index),
        )
    await storage.messages.add(
        id="outcome",
        conversation_id="later",
        role="user",
        content="已经打完了，很顺利",
        timestamp=begin + timedelta(days=7),
    )
    history = PersonalHistory(profile.root / "missing", Path(db.db_path))
    context = history.context(
        "第二针后来怎么样了",
        profile_content=(
            "- 猫咪第二针准备周末去打；事件名称：第二针疫苗；状态：planned；"
            "事件ID：evt-second；来源：message:plan"
        ),
    )
    assert "message:outcome" in context
    assert "已经打完了" in context


async def test_large_dossier_uses_relevant_sources_without_loading_every_old_turn(memory):
    profile, storage, db = memory
    from datetime import UTC, datetime, timedelta

    begin = datetime(2026, 6, 1, tzinfo=UTC)
    lines = []
    for index in range(50):
        chat = f"chat{index}"
        await storage.conversations.create(id=chat, platform="web", user_id="local-single-user")
        text = "猫咪的疫苗已经打完了" if index == 49 else f"第{index}次锻炼是跑步"
        await storage.messages.add(
            id=f"source{index}",
            conversation_id=chat,
            role="user",
            content=text,
            timestamp=begin + timedelta(minutes=index),
        )
        lines.append(f"- {text}；来源：message:source{index}")
    history = PersonalHistory(profile.root / "missing", Path(db.db_path))
    context = history.context("猫咪疫苗后来怎么样", profile_content="\n".join(lines))
    assert "message:source49" in context
    assert "message:source0" not in context


async def test_history_budget_keeps_relevant_outcome_and_reports_other_sources(memory):
    profile, storage, db = memory
    from datetime import UTC, datetime, timedelta

    begin = datetime(2026, 6, 1, tzinfo=UTC)
    lines = []
    for index in range(15):
        chat = f"story{index}"
        await storage.conversations.create(id=chat, platform="web", user_id="local-single-user")
        content = "已经打完第二针疫苗" if index == 14 else "猫咪第二针疫苗准备中"
        content += "详细经历" * 700
        await storage.messages.add(
            id=f"story{index}",
            conversation_id=chat,
            role="user",
            content=content,
            timestamp=begin + timedelta(minutes=index),
        )
        lines.append(
            f"- {content[:16]}；事件ID：evt-vaccine；事件名称：第二针疫苗；"
            f"来源：message:story{index}"
        )
    history = PersonalHistory(profile.root / "missing", Path(db.db_path))
    context = history.context("第二针疫苗已经打完了吗", profile_content="\n".join(lines))
    assert "message:story14" in context
    assert "未展开" in context
    assert len(context) < 50_000


async def test_cross_conversation_explicit_event_reference_finds_outcome(memory):
    profile, storage, db = memory
    from datetime import UTC, datetime, timedelta

    begin = datetime(2026, 6, 1, tzinfo=UTC)
    for name in ("plan-chat", "result-chat"):
        await storage.conversations.create(id=name, platform="web", user_id="local-single-user")
    await storage.messages.add(
        id="plan-cross",
        conversation_id="plan-chat",
        role="user",
        content="猫咪第二针准备周末去打",
        timestamp=begin,
    )
    await storage.messages.add(
        id="result-cross",
        conversation_id="result-chat",
        role="user",
        content="猫咪的第二针已经打完了，很顺利",
        timestamp=begin + timedelta(days=7),
    )
    history = PersonalHistory(profile.root / "missing", Path(db.db_path))
    context = history.context(
        "第二针后来怎么样",
        profile_content=(
            "- 猫咪第二针准备周末去打；事件名称：第二针疫苗；状态：planned；"
            "事件ID：evt-second；来源：message:plan-cross"
        ),
    )
    assert "message:result-cross" in context


async def test_followup_receipt_retries_and_suppresses_paraphrased_question_after_restart(memory):
    profile, storage, _ = memory
    base = dict(
        topic="宠物",
        subject="猫咪",
        kind="event",
        event_name="第二针",
        fact="计划接种",
        status="planned",
        stage="decision",
        followup_field="接种结果",
        followup_question="猫咪第二针打了吗？",
    )
    await profile.add_claim(base, source="message:plan", stated_at="2026-06-01")
    event_id = event_identity("宠物/猫咪.md", "第二针")

    class Gateway:
        fail = False

        async def chat(self, messages):
            if self.fail:
                raise ValueError("offline")
            return SimpleNamespace(text=json.dumps([{"event_id": event_id}]))

    gateway = Gateway()
    service = PersonalFollowups(profile=profile, repository=storage.followups, gateway=gateway)
    context = profile.context("猫咪")
    assert "猫咪第二针打了吗？" in await service.context(
        "猫咪疫苗", profile_context=context, history_context="用户说计划去打疫苗"
    )
    assert await storage.followups.asked() == set()  # Offering/generating is not delivery.
    gateway.fail = True
    await service.confirm_delivery("chat", "那次计划的接种后来进行得怎么样", "delivered1")
    assert len(await storage.followups.pending()) == 1
    assert "没有允许" in await service.context(
        "猫咪疫苗", profile_context=context, history_context="x"
    )
    gateway.fail = False
    service = PersonalFollowups(profile=profile, repository=storage.followups, gateway=gateway)
    assert "没有允许" in await service.context(
        "猫咪疫苗", profile_context=context, history_context="x"
    )
    assert await storage.followups.asked() == {(event_id, "接种结果")}
    assert await storage.followups.pending() == []
    await profile.add_claim(
        dict(base, fact="接种计划已取消", status="cancelled", stage="outcome"),
        source="message:cancel",
        stated_at="2026-06-02",
    )
    assert "没有允许" in await service.context(
        "猫咪疫苗", profile_context=profile.context("猫咪"), history_context="用户取消了"
    )
    async with storage.followups._db.get_connection() as conn:
        row = await (await conn.execute("SELECT answered_source FROM memory_followups")).fetchone()
    assert row[0] == "message:cancel"


async def test_mixed_turn_general_failure_retries_without_reextracting_personal_claims(memory):
    profile, storage, db = memory

    class Gateway:
        calls = 0

        async def chat(self, messages):
            self.calls += 1
            if "个人档案" in messages[0]["content"]:
                return SimpleNamespace(
                    text=json.dumps(
                        [
                            dict(
                                topic="个人",
                                subject="交流偏好",
                                kind="confirmed",
                                fact="语言：中文",
                                preference_key="language",
                                scope="通用",
                            )
                        ]
                    )
                )
            return SimpleNamespace(
                text=json.dumps([dict(category="concept", content="二分查找需要有序数据")])
            )

    gateway = Gateway()
    semantic = SemanticMemory(storage, gateway, NullEmbeddingService(), db)
    sync = PersonalMemorySync(
        profile=profile, semantic=semantic, gateway=gateway, progress=storage.personal_progress
    )
    original = semantic.store_extracted_knowledge

    async def failing(*args, **kwargs):
        raise ValueError("temporary write failure")

    semantic.store_extracted_knowledge = failing
    user = dict(
        id="user1",
        conversation_id="chat",
        content="以后用中文。二分查找需要有序数据。",
        role="user",
        timestamp="2026-06-01",
    )
    assistant = dict(role="assistant", content="好的")
    with pytest.raises(ValueError, match="temporary"):
        await sync.sync_turn(user, assistant, adjacent=[])
    assert (await storage.personal_progress.stage("message:user1", "personal"))[1]
    assert not (await storage.personal_progress.stage("message:user1", "general"))[1]
    calls = gateway.calls
    semantic.store_extracted_knowledge = original
    await sync.sync_turn(user, assistant, adjacent=[])
    await sync.sync_turn(user, assistant, adjacent=[])
    assert gateway.calls == calls
    assert len(await storage.knowledge.list_all()) == 1
    assert "语言：中文" in profile.preference_context("算法问题")


async def test_revision_conflict_reextracts_and_preserves_manual_edit(memory):
    profile, storage, _ = memory
    await profile.add_claim(
        dict(topic="个人", subject="滔", kind="confirmed", fact="称呼：滔"),
        source="message:old",
        stated_at="2026-01-01",
    )
    path = profile.root / "个人/滔.md"

    class Gateway:
        calls = 0

        async def chat(self, messages):
            self.calls += 1
            if self.calls == 1:
                path.write_text(path.read_text() + "\n人工补充：保留这一行\n")
            return SimpleNamespace(
                text=json.dumps(
                    [dict(topic="个人", subject="滔", kind="confirmed", fact="语言：中文")]
                )
            )

    class Semantic:
        calls = 0

        async def extract_items(self, messages):
            self.calls += 1
            return []

        async def store_extracted_knowledge(self, *args, **kwargs):
            pass

    gateway, semantic = Gateway(), Semantic()
    sync = PersonalMemorySync(
        profile=profile, semantic=semantic, gateway=gateway, progress=storage.personal_progress
    )
    user = dict(
        id="edited", role="user", content="用中文", timestamp="2026-06-01", conversation_id="chat"
    )
    with pytest.raises(RuntimeError, match="changed since extraction"):
        await sync.sync_turn(user, dict(role="assistant", content="好的"), adjacent=[])
    assert await storage.personal_progress.stage("message:edited", "personal") is None
    await sync.sync_turn(user, dict(role="assistant", content="好的"), adjacent=[])
    assert "人工补充：保留这一行" in path.read_text()
    assert path.read_text().count("语言：中文") == 1
    assert gateway.calls == 2 and semantic.calls == 1
    assert (await storage.personal_progress.stage("message:edited", "personal"))[1]


async def test_delivery_ids_are_scoped_by_conversation(memory):
    profile, storage, db = memory
    await profile.add_claim(
        dict(
            topic="宠物",
            subject="猫",
            kind="event",
            fact="明天去接种",
            status="planned",
            event_name="接种",
            stage="decision",
            followup_field="result",
            followup_question="后来接种了吗？",
        ),
        source="message:plan",
        stated_at="2026-06-01",
    )

    class Gateway:
        async def chat(self, messages):
            raise ValueError("temporarily unavailable")

    followups = PersonalFollowups(profile=profile, repository=storage.followups, gateway=Gateway())
    await followups.confirm_delivery("telegram:a", "后来接种了吗？", "42")
    await followups.confirm_delivery("telegram:b", "后来接种了吗？", "42")
    assert {item["id"] for item in await storage.followups.pending()} == {
        "telegram:a:42",
        "telegram:b:42",
    }


async def test_same_statement_orders_event_dates_without_reversing_status(memory):
    profile, _, _ = memory
    for fact, event_time, status, stage in (
        ("上个月打了第一针", "2026-06-28", "done", "outcome"),
        ("明天打第二针", "2026-08-01", "planned", "decision"),
    ):
        await profile.add_claim(
            dict(
                topic="宠物",
                subject="猫",
                kind="event",
                fact=fact,
                event_time=event_time,
                status=status,
                event_name="疫苗",
                stage=stage,
            ),
            source="message:both",
            stated_at="2026-07-31",
        )
    assert profile.events()[0].status == "planned"


def test_history_neighbours_use_absolute_time_across_archive_timezones(tmp_path):
    from src.memory.personal_history import HistoryHit

    history = PersonalHistory(tmp_path / "archive", tmp_path / "absent.db")
    history._records = {
        "first": HistoryHit("first", "先讨论", "2026-06-01T09:00:00+08:00", conversation_id="c"),
        "second": HistoryHit("second", "再决定", "2026-06-01T02:00:00+00:00", conversation_id="c"),
    }
    assert [hit.source for hit in history._neighbours({"second"})] == ["first", "second"]


async def test_relative_profile_root_supports_extracted_existing_document(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    profile = PersonalProfile(Path("data/personal_memory"))
    await profile.add_claim(
        dict(topic="宠物", subject="猫", kind="confirmed", fact="品种：布偶"),
        source="message:old",
        stated_at="2026-01-01",
    )

    class Gateway:
        async def chat(self, messages):
            return SimpleNamespace(
                text=json.dumps(
                    [dict(topic="宠物", subject="猫", kind="event", fact="体重：2.9kg")]
                )
            )

    claims = await profile.extract(Gateway(), "它2.9kg", stated_at="2026-09-17")
    assert await profile.apply_claims(claims, source="message:new", stated_at="2026-09-17") == 1
    assert "2.9kg" in profile.read_document("宠物/猫.md")[0]
