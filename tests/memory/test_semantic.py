from __future__ import annotations

import json
import math
from types import SimpleNamespace

import pytest

from src.memory.semantic import (
    SemanticMemory,
    _l2_distance_to_cosine_similarity,
    _normalize_embedding,
)


class _FakeCursor:
    def __init__(self, row: object) -> None:
        self._row = row

    async def fetchone(self) -> object:
        return self._row


class _FakeConnection:
    def __init__(self, row: object = None) -> None:
        self._row = row
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    async def execute(self, sql: str, params: tuple[object, ...]) -> _FakeCursor:
        self.calls.append((sql, params))
        return _FakeCursor(self._row)

    async def commit(self) -> None:
        return None


class _ConnectionContext:
    def __init__(self, connection: _FakeConnection) -> None:
        self._connection = connection

    async def __aenter__(self) -> _FakeConnection:
        return self._connection

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False


class _FakeDatabase:
    def __init__(self, connection: _FakeConnection) -> None:
        self._connection = connection

    def get_connection(self) -> _ConnectionContext:
        return _ConnectionContext(self._connection)


class _FakeKnowledgeRepo:
    def __init__(self) -> None:
        self._items = {
            "dup-1": {"id": "dup-1", "content": "Existing knowledge", "priority": "P1"},
        }

    async def get(self, knowledge_id: str) -> dict[str, str] | None:
        return self._items.get(knowledge_id)


def _build_semantic_memory(connection: _FakeConnection) -> SemanticMemory:
    storage = SimpleNamespace(knowledge=_FakeKnowledgeRepo())
    return SemanticMemory(
        storage=storage,
        model_gateway=object(),
        embedding_service=object(),
        db=_FakeDatabase(connection),
    )


def test_normalize_embedding_returns_unit_vector() -> None:
    normalized = _normalize_embedding([3.0, 4.0])

    assert normalized == [0.6, 0.8]


def test_l2_distance_to_cosine_similarity_matches_normalized_geometry() -> None:
    assert _l2_distance_to_cosine_similarity(0.0) == 1.0
    assert _l2_distance_to_cosine_similarity(math.sqrt(2)) == pytest.approx(0.0)


async def test_find_duplicate_uses_normalized_l2_similarity() -> None:
    semantic = _build_semantic_memory(_FakeConnection(row=("dup-1", 0.5)))

    result = await semantic._find_duplicate([10.0, 0.0], "new content")

    assert result is not None
    assert result["id"] == "dup-1"


async def test_store_embedding_normalizes_before_persisting() -> None:
    connection = _FakeConnection()
    semantic = _build_semantic_memory(connection)

    await semantic._store_embedding("kid-1", [3.0, 4.0])

    stored_payload = connection.calls[0][1][1]
    assert json.loads(stored_payload) == [0.6, 0.8]
