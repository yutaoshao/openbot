from __future__ import annotations

from dataclasses import dataclass

from fastapi.testclient import TestClient

from src.api.app import create_api_app


@dataclass
class _FakeAgentResponse:
    content: str
    model: str
    latency_ms: int
    tokens_in: int
    tokens_out: int


class _FakeAgent:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    async def run(
        self,
        input_text: str,
        conversation_id: str = "",
        platform: str = "unknown",
    ) -> _FakeAgentResponse:
        self.calls.append((input_text, conversation_id, platform))
        return _FakeAgentResponse(
            content=f"echo:{input_text}",
            model="fake-model",
            latency_ms=12,
            tokens_in=3,
            tokens_out=5,
        )


def test_health_returns_ok() -> None:
    client = TestClient(create_api_app(), client=("127.0.0.1", 50000))

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["runtime"]["api"]["status"] == "ready"


def test_chat_returns_503_when_agent_is_missing() -> None:
    client = TestClient(create_api_app(agent=None), client=("127.0.0.1", 50000))

    response = client.post(
        "/api/chat",
        json={"message": "hello"},
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "Agent is not initialized for API requests."


def test_chat_returns_agent_output() -> None:
    fake_agent = _FakeAgent()
    client = TestClient(create_api_app(agent=fake_agent), client=("127.0.0.1", 50000))

    response = client.post(
        "/api/chat",
        json={
            "message": "hi",
            "conversation_id": "conv-123",
            "platform": "web",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "reply": "echo:hi",
        "conversation_id": "conv-123",
        "model": "fake-model",
        "latency_ms": 12,
        "tokens_in": 3,
        "tokens_out": 5,
    }
    assert fake_agent.calls == [("hi", "conv-123", "web")]


def test_chat_generates_conversation_id_when_missing() -> None:
    fake_agent = _FakeAgent()
    client = TestClient(create_api_app(agent=fake_agent), client=("127.0.0.1", 50000))

    response = client.post(
        "/api/chat",
        json={
            "message": "hello",
            "platform": "web",
        },
    )

    assert response.status_code == 200
    body = response.json()
    generated = body["conversation_id"]
    assert isinstance(generated, str)
    assert len(generated) > 0
    assert fake_agent.calls == [("hello", generated, "web")]


def test_chat_rejects_blank_messages() -> None:
    fake_agent = _FakeAgent()
    client = TestClient(create_api_app(agent=fake_agent), client=("127.0.0.1", 50000))

    response = client.post(
        "/api/chat",
        json={"message": "   "},
    )

    assert response.status_code == 422
    assert fake_agent.calls == []


def test_chat_rejects_overly_long_messages() -> None:
    fake_agent = _FakeAgent()
    client = TestClient(create_api_app(agent=fake_agent), client=("127.0.0.1", 50000))

    response = client.post(
        "/api/chat",
        json={"message": "x" * 32001},
    )

    assert response.status_code == 422
    assert fake_agent.calls == []
