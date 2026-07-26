from __future__ import annotations

import asyncio
from dataclasses import dataclass
from types import SimpleNamespace

from fastapi import Request
from fastapi.testclient import TestClient

from src.agent.coordination import UserExecutionCoordinator
from src.api.app import create_api_app
from src.api.routes.chat import post_chat
from src.api.schemas import ChatRequest


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


class _ConcurrentAgent:
    def __init__(self) -> None:
        self.active_calls = 0
        self.max_active_calls = 0
        self.first_turn_started = asyncio.Event()
        self.release_first_turn = asyncio.Event()

    async def run(
        self,
        input_text: str,
        conversation_id: str = "",
        platform: str = "unknown",
    ) -> _FakeAgentResponse:
        self.active_calls += 1
        self.max_active_calls = max(self.max_active_calls, self.active_calls)
        try:
            if input_text == "first":
                self.first_turn_started.set()
                await self.release_first_turn.wait()
            await asyncio.sleep(0)
            return _FakeAgentResponse(input_text, "fake-model", 1, 1, 1)
        finally:
            self.active_calls -= 1


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


async def test_chat_serializes_single_user_turns_across_conversations() -> None:
    concurrent_agent = _ConcurrentAgent()
    shared_coordinator = UserExecutionCoordinator()
    application = SimpleNamespace(execution_coordinator=shared_coordinator)
    app = create_api_app(agent=concurrent_agent, application=application)
    request = Request({"type": "http", "app": app})
    first_payload = ChatRequest(message="first", conversation_id="first-conv")
    second_payload = ChatRequest(message="second", conversation_id="second-conv")

    assert app.state.execution_coordinator is shared_coordinator
    first_turn = asyncio.create_task(post_chat(first_payload, request))
    await concurrent_agent.first_turn_started.wait()
    second_turn = asyncio.create_task(post_chat(second_payload, request))
    await asyncio.sleep(0)

    assert concurrent_agent.max_active_calls == 1
    concurrent_agent.release_first_turn.set()
    first_response, second_response = await asyncio.gather(first_turn, second_turn)
    assert first_response.reply == "first"
    assert second_response.reply == "second"
    assert concurrent_agent.max_active_calls == 1


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
