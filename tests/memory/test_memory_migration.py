from __future__ import annotations

import json
import sqlite3
from types import SimpleNamespace

import pytest

from src.core.config import StorageConfig
from src.infrastructure.database import Database
from src.infrastructure.storage import Storage
from src.memory.maintenance import audit_legacy


async def test_v9_knowledge_is_explicitly_unreviewed_and_text_is_preserved(tmp_path):
    path = tmp_path / "old.db"
    with sqlite3.connect(path) as conn:
        conn.executescript("""
            CREATE TABLE schema_version(version INTEGER, applied_at TEXT);
            INSERT INTO schema_version VALUES (9, '2026-09-27');
            CREATE TABLE knowledge (
                id TEXT PRIMARY KEY, user_id TEXT, source_conversation_id TEXT,
                category TEXT, content TEXT, tags TEXT, priority TEXT, confidence REAL,
                access_count INTEGER, created_at TEXT, updated_at TEXT, expires_at TEXT
            );
            INSERT INTO knowledge VALUES ('old','local-single-user',NULL,'fact','旧个人事实',
                                           '[]','P0',1,0,'2026-09-01','2026-09-01',NULL);
        """)
    db = Database(StorageConfig(db_path=str(path)))
    await db.initialize()
    try:
        storage = Storage(db)
        old = await storage.knowledge.get("old")
        assert old["content"] == "旧个人事实"
        assert old["memory_type"] == "legacy_unreviewed"
        assert await storage.knowledge.search("个人", memory_type="general") == []
        await storage.knowledge.add(
            id="new", user_id="local-single-user", category="concept", content="通用知识"
        )
        assert (await storage.knowledge.get("new"))["memory_type"] == "general"
        assert [item["id"] for item in await storage.knowledge.list_all(memory_type="general")] == [
            "new"
        ]
    finally:
        await db.close()


async def test_legacy_audit_requires_complete_classification_and_can_resume(tmp_path):
    db = Database(StorageConfig(db_path=str(tmp_path / "memory.db")))
    await db.initialize()
    try:
        storage = Storage(db)
        for index, content in enumerate(("一般概念", "用户经历")):
            await storage.knowledge.add(
                id=str(index),
                user_id="local-single-user",
                category="fact",
                content=content,
                memory_type="legacy_unreviewed",
            )

        class Gateway:
            incomplete = True
            calls = 0

            async def chat(self, messages):
                self.calls += 1
                items = json.loads(messages[1]["content"])
                return SimpleNamespace(
                    text=json.dumps(
                        [
                            {
                                "index": item["index"],
                                "memory_type": "general"
                                if item["content"] == "一般概念"
                                else "personal_legacy",
                            }
                            for item in (items[:1] if self.incomplete else items)
                        ]
                    )
                )

        gateway = Gateway()
        report = tmp_path / "report.json"
        with pytest.raises(RuntimeError, match="failed batches"):
            await audit_legacy(storage, gateway, report)
        assert (await storage.knowledge.get("0"))["memory_type"] == "legacy_unreviewed"
        gateway.incomplete = False
        assert await audit_legacy(storage, gateway, report) == {"general": 1, "personal_legacy": 1}
        calls = gateway.calls
        await audit_legacy(storage, gateway, report)
        assert gateway.calls == calls
        assert (await storage.knowledge.get("1"))["content"] == "用户经历"
    finally:
        await db.close()


async def test_general_vector_recall_filters_legacy_before_nearest_limit(tmp_path):
    from src.infrastructure.embedding import NullEmbeddingService
    from src.memory.semantic.service import SemanticMemory

    db = Database(StorageConfig(db_path=str(tmp_path / "vectors.db")), embedding_dimensions=2)
    await db.initialize()
    try:
        storage = Storage(db)
        semantic = SemanticMemory(storage, None, NullEmbeddingService(), db)
        # Cross a vec0 storage chunk, as in an upgraded database.
        for index in range(1030):
            key = f"legacy-{index}"
            await storage.knowledge.add(
                id=key,
                user_id="local-single-user",
                category="fact",
                content="旧个人信息",
                memory_type="personal_legacy",
            )
            await semantic._store_embedding(key, [1.0, 0.0])
        await storage.knowledge.add(
            id="general",
            user_id="local-single-user",
            category="concept",
            content="一般知识",
            memory_type="general",
        )
        await semantic._store_embedding("general", [0.9, 0.1])
        results = await semantic._vector_search([1.0, 0.0], 1, "local-single-user")
        assert [item["id"] for item in results] == ["general"]
    finally:
        await db.close()
