from __future__ import annotations

from fastapi.testclient import TestClient

from src.api.app import create_api_app


class _FakeConversationRepo:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    async def list_recent(self, limit: int = 20, offset: int = 0) -> list[dict]:
        return self._rows[offset:offset + limit]

    async def search(self, query: str, limit: int = 10) -> list[dict]:
        matched = [
            row for row in self._rows
            if query in (row.get("title") or "") or query in (row.get("summary") or "")
        ]
        return matched[:limit]

    async def get(self, conversation_id: str) -> dict | None:
        for row in self._rows:
            if row["id"] == conversation_id:
                return row
        return None

    async def delete(self, conversation_id: str) -> None:
        self._rows = [row for row in self._rows if row["id"] != conversation_id]


class _FakeMessageRepo:
    def __init__(self, messages_by_conv: dict[str, list[dict]]) -> None:
        self._messages_by_conv = messages_by_conv

    async def count_by_conversation(self, conversation_id: str) -> int:
        return len(self._messages_by_conv.get(conversation_id, []))

    async def count_by_conversations(
        self, conversation_ids: list[str],
    ) -> dict[str, int]:
        return {
            cid: len(self._messages_by_conv.get(cid, []))
            for cid in conversation_ids
        }

    async def get_by_conversation(
        self,
        conversation_id: str,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[dict]:
        items = self._messages_by_conv.get(conversation_id, [])
        if limit is None:
            return items[offset:]
        return items[offset:offset + limit]


class _FakeStorage:
    def __init__(self) -> None:
        conversations = [
            {
                "id": "conv-1",
                "title": "Project overview",
                "summary": "Discussed API phase",
                "platform": "telegram",
                "created_at": "2026-03-19T00:00:00Z",
                "updated_at": "2026-03-19T00:10:00Z",
            },
            {
                "id": "conv-2",
                "title": "Memory tuning",
                "summary": "Embedding provider",
                "platform": "web",
                "created_at": "2026-03-19T01:00:00Z",
                "updated_at": "2026-03-19T01:05:00Z",
            },
        ]
        messages_by_conv = {
            "conv-1": [
                {
                    "id": "m-1",
                    "conversation_id": "conv-1",
                    "role": "user",
                    "content": "hi",
                    "model": None,
                    "tokens_in": None,
                    "tokens_out": None,
                    "latency_ms": None,
                    "tool_calls": None,
                    "metadata": None,
                    "created_at": "2026-03-19T00:00:01Z",
                },
                {
                    "id": "m-2",
                    "conversation_id": "conv-1",
                    "role": "assistant",
                    "content": "hello",
                    "model": "kimi-k2.5",
                    "tokens_in": 10,
                    "tokens_out": 8,
                    "latency_ms": 450,
                    "tool_calls": [],
                    "metadata": {},
                    "created_at": "2026-03-19T00:00:03Z",
                },
            ],
            "conv-2": [],
        }
        self.conversations = _FakeConversationRepo(conversations)
        self.messages = _FakeMessageRepo(messages_by_conv)


def test_list_conversations_returns_recent_items() -> None:
    client = TestClient(create_api_app(storage=_FakeStorage()))

    response = client.get("/api/conversations?limit=10&offset=0")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 2
    assert body[0]["id"] == "conv-1"
    assert body[0]["message_count"] == 2
    assert body[1]["id"] == "conv-2"
    assert body[1]["message_count"] == 0


def test_list_conversations_supports_search_query() -> None:
    client = TestClient(create_api_app(storage=_FakeStorage()))

    response = client.get("/api/conversations?q=Memory&limit=10&offset=0")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["id"] == "conv-2"


def test_conversation_detail_returns_conversation_and_messages() -> None:
    client = TestClient(create_api_app(storage=_FakeStorage()))

    response = client.get("/api/conversations/conv-1")

    assert response.status_code == 200
    body = response.json()
    assert body["conversation"]["id"] == "conv-1"
    assert body["conversation"]["message_count"] == 2
    assert [item["id"] for item in body["messages"]] == ["m-1", "m-2"]


def test_conversation_detail_returns_404_for_missing_id() -> None:
    client = TestClient(create_api_app(storage=_FakeStorage()))

    response = client.get("/api/conversations/not-found")

    assert response.status_code == 404
    assert response.json()["detail"] == "Conversation not found"


def test_conversations_returns_503_when_storage_is_missing() -> None:
    client = TestClient(create_api_app(storage=None))

    response = client.get("/api/conversations")

    assert response.status_code == 503
    assert response.json()["detail"] == "Storage is not initialized for API requests."


def test_conversation_delete_works() -> None:
    client = TestClient(create_api_app(storage=_FakeStorage()))

    response = client.delete("/api/conversations/conv-1")

    assert response.status_code == 200
    assert response.json()["status"] == "deleted"
