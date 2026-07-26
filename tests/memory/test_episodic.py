from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

from src.agent.turn_outcome import FailedTurn
from src.infrastructure.model_gateway import ModelResponse
from src.memory.episodic import EpisodicMemory, _normalize_embedding
from src.memory.episodic.helpers import sanitize_title


class _FakeConnection:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    async def execute(self, sql: str, params: tuple[object, ...]) -> None:
        self.calls.append((sql, params))
        return None

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


class _FakeEmbeddingService:
    async def embed(self, text: str) -> list[float]:
        return [3.0, 4.0]


class _RecordingGateway:
    def __init__(self, text: str) -> None:
        self.text = text
        self.calls: list[list[dict[str, str]]] = []

    async def chat(self, messages: list[dict[str, str]]) -> ModelResponse:
        self.calls.append(messages)
        return ModelResponse(text=self.text)


class _MessageStorage:
    def __init__(self, messages: list[dict[str, Any]]) -> None:
        self._messages = messages

    async def get_by_conversation(self, _conversation_id: str) -> list[dict[str, Any]]:
        return list(self._messages)


class _ConversationStorage:
    def __init__(self) -> None:
        self.updates: list[tuple[str, dict[str, str]]] = []

    async def update(self, conversation_id: str, **fields: str) -> None:
        self.updates.append((conversation_id, fields))


def test_normalize_embedding_returns_unit_vector() -> None:
    assert _normalize_embedding([3.0, 4.0]) == [0.6, 0.8]


async def test_store_embedding_normalizes_before_persisting() -> None:
    connection = _FakeConnection()
    episodic = EpisodicMemory(
        storage=SimpleNamespace(),
        model_gateway=object(),
        embedding_service=_FakeEmbeddingService(),
        db=_FakeDatabase(connection),
    )

    await episodic._store_embedding("conv-1", "summary")

    insert_sql, insert_params = connection.calls[1]
    assert "INSERT INTO conversation_embeddings" in insert_sql
    assert json.loads(insert_params[1]) == [0.6, 0.8]


async def test_generate_title_sends_transcript_as_final_user_message() -> None:
    gateway = _RecordingGateway("Short title")
    episodic = EpisodicMemory(
        storage=SimpleNamespace(),
        model_gateway=gateway,
        embedding_service=_FakeEmbeddingService(),
        db=_FakeDatabase(_FakeConnection()),
    )

    title = await episodic.generate_title(
        [
            {"role": "user", "content": "Please summarize this project."},
            {"role": "assistant", "content": "Sure, here is the report."},
        ]
    )

    assert title == "Short title"
    assert gateway.calls[0][-1]["role"] == "user"
    assert "Conversation opening:" in gateway.calls[0][-1]["content"]


async def test_generate_summary_sends_transcript_as_final_user_message() -> None:
    gateway = _RecordingGateway("Two sentence summary.")
    episodic = EpisodicMemory(
        storage=SimpleNamespace(),
        model_gateway=gateway,
        embedding_service=_FakeEmbeddingService(),
        db=_FakeDatabase(_FakeConnection()),
    )

    summary = await episodic.generate_summary(
        [
            {"role": "user", "content": "Question"},
            {"role": "assistant", "content": "Answer"},
        ]
    )

    assert summary == "Two sentence summary."
    assert gateway.calls[0][-1]["role"] == "user"
    assert "Conversation transcript:" in gateway.calls[0][-1]["content"]


async def test_conversation_archive_excludes_failed_turns() -> None:
    failure_metadata = FailedTurn("failed reply", reason="stop_verification").message_metadata()
    message_storage = _MessageStorage(
        [
            {"role": "user", "content": "failed request"},
            {
                "role": "assistant",
                "content": "failed reply",
                "metadata": failure_metadata,
            },
            {"role": "user", "content": "completed request"},
            {"role": "assistant", "content": "completed reply"},
        ]
    )
    conversation_storage = _ConversationStorage()
    gateway = _RecordingGateway("Archived conversation")
    episodic = EpisodicMemory(
        storage=SimpleNamespace(messages=message_storage, conversations=conversation_storage),
        model_gateway=gateway,
        embedding_service=_FakeEmbeddingService(),
        db=_FakeDatabase(_FakeConnection()),
    )

    await episodic.on_conversation_end("conv-1", "user-1")

    prompts = "\n".join(message["content"] for call in gateway.calls for message in call)
    assert "failed request" not in prompts
    assert "failed reply" not in prompts
    assert "completed request" in prompts
    assert "completed reply" in prompts
    assert conversation_storage.updates


def test_sanitize_title_normalizes_markdown_and_whitespace() -> None:
    assert sanitize_title('  "**Identity**\\n limits"  ') == "Identity limits"


def test_sanitize_title_falls_back_for_empty_or_sentence_like_titles() -> None:
    assert sanitize_title('""') == "Untitled conversation"
    assert (
        sanitize_title("好问题！根据系统提供的信息，我能看到简短的对话摘要。")
        == "Untitled conversation"
    )
