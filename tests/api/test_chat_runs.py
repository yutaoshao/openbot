from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace

import httpx
import pytest

from src.agent.coordination import UserExecutionCoordinator
from src.api.app import create_api_app
from src.application.chat_runs import ChatRunConflictError, ChatRunManager
from src.infrastructure.model_gateway import StreamChunk


class _Agent:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.cleaning = asyncio.Event()
        self.cleaned = asyncio.Event()
        self.cleaned.set()
        self.calls: list[tuple[str, str]] = []
        self.deliveries: list[str] = []

    async def run_stream(self, message: str, *, conversation_id: str, **_kwargs):
        self.calls.append((message, conversation_id))
        yield StreamChunk(type="text", text="partial")
        self.started.set()
        try:
            await self.release.wait()
            yield StreamChunk(type="done", turn_outcome="completed")
        finally:
            self.cleaning.set()
            await self.cleaned.wait()

    async def confirm_delivery(self, _conversation_id: str, _text: str, run_id: str) -> None:
        self.deliveries.append(run_id)


def _submit(manager, message="hello", conversation_id="conv", request_id=None):
    return manager.start(
        message=message, conversation_id=conversation_id, request_id=request_id or str(uuid.uuid4())
    )


async def _terminal(manager, run_id):
    async def wait():
        while manager.get(run_id)["status"] not in {"completed", "cancelled", "failed"}:
            await asyncio.sleep(0)
        return manager.get(run_id)

    return await asyncio.wait_for(wait(), 1)


async def test_request_id_is_idempotent_and_conflicting_payload_is_rejected() -> None:
    agent = _Agent()
    manager = ChatRunManager(agent, UserExecutionCoordinator())
    request_id = str(uuid.uuid4())
    first = _submit(manager, request_id=request_id)
    second = _submit(manager, request_id=request_id)
    assert second == first
    with pytest.raises(ChatRunConflictError, match="different message"):
        _submit(manager, message="different", request_id=request_id)
    await agent.started.wait()
    assert len(agent.calls) == 1
    assert manager.list(request_id=request_id)[0]["run_id"] == first["run_id"]
    assert manager.list(request_id=str(uuid.uuid4())) == []
    await manager.stop_all()


async def test_queued_stop_never_executes_and_keeps_global_user_serialization() -> None:
    agent = _Agent()
    coordinator = UserExecutionCoordinator()
    manager = ChatRunManager(agent, coordinator)
    first = _submit(manager, conversation_id="first")
    await agent.started.wait()
    second = _submit(manager, conversation_id="second")
    await asyncio.sleep(0)
    assert manager.get(second["run_id"])["status"] == "queued"
    assert manager.stop(second["run_id"])["status"] == "cancelled"
    agent.release.set()
    assert (await _terminal(manager, first["run_id"]))["status"] == "completed"
    assert agent.calls == [("hello", "first")]
    await manager.stop_all()


async def test_stop_waits_for_cleanup_is_idempotent_and_cannot_cancel_new_run() -> None:
    agent = _Agent()
    agent.cleaned.clear()
    manager = ChatRunManager(agent, UserExecutionCoordinator())
    first = _submit(manager)
    await agent.started.wait()
    assert manager.stop(first["run_id"])["status"] == "stopping"
    await agent.cleaning.wait()
    assert manager.stop(first["run_id"])["status"] == "stopping"
    assert manager.busy
    agent.cleaned.set()
    stopped = await _terminal(manager, first["run_id"])
    assert stopped["status"] == "cancelled"
    assert stopped["text"] == "partial"
    assert not manager.busy
    second = _submit(manager, conversation_id="next")
    assert manager.stop(first["run_id"])["status"] == "cancelled"
    agent.release.set()
    assert (await _terminal(manager, second["run_id"]))["status"] == "completed"
    await manager.stop_all()


async def test_run_rejects_new_admission_and_deletion_conflicts() -> None:
    coordinator = UserExecutionCoordinator()
    manager = ChatRunManager(_Agent(), coordinator)
    assert coordinator.pause_if_idle()
    with pytest.raises(ChatRunConflictError, match="restarting"):
        _submit(manager)
    coordinator.resume()
    manager.begin_delete("conv")
    with pytest.raises(ChatRunConflictError, match="deleted"):
        _submit(manager)
    manager.end_delete("conv")
    run = _submit(manager)
    with pytest.raises(ChatRunConflictError, match="active turn"):
        manager.begin_delete("conv")
    await manager.stop_all()
    assert manager.get(run["run_id"])["status"] == "cancelled"


async def test_failed_agent_outcome_is_not_reported_completed() -> None:
    class FailedAgent:
        async def run_stream(self, *_args, **_kwargs):
            yield StreamChunk(type="text", text="The write could not be verified")
            yield StreamChunk(
                type="done", turn_outcome="failed", failure_reason="stop_verification"
            )

    manager = ChatRunManager(FailedAgent(), UserExecutionCoordinator())
    run = _submit(manager)
    result = await _terminal(manager, run["run_id"])
    assert result["status"] == "failed"
    assert result["error"] == "stop_verification"
    assert result["text"] == "The write could not be verified"
    await manager.stop_all()


async def test_snapshots_cannot_mutate_running_state() -> None:
    class ToolAgent(_Agent):
        async def run_stream(self, *_args, **_kwargs):
            yield StreamChunk(type="tool_status", tool_name="bash")
            self.started.set()
            await self.release.wait()
            yield StreamChunk(type="done")

    agent = ToolAgent()
    manager = ChatRunManager(agent, UserExecutionCoordinator())
    run = _submit(manager)
    await agent.started.wait()
    snapshot = manager.get(run["run_id"])
    snapshot["tool_events"][0]["status"] = "forged"
    assert manager.get(run["run_id"])["tool_events"][0]["status"] == "running"
    await manager.stop_all()
    assert manager.get(run["run_id"])["tool_events"][0]["status"] == "interrupted"


async def test_rest_reconnect_reads_same_run_without_replaying_and_acknowledges_delivery() -> None:
    agent = _Agent()
    manager = ChatRunManager(agent, UserExecutionCoordinator())
    app = create_api_app(agent=agent)
    app.state.chat_runs = manager
    transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 12345))
    request_id = str(uuid.uuid4())
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
        response = await client.post(
            "/api/chat/runs", json={"message": "hello", "request_id": request_id}
        )
        assert response.status_code == 200
        run_id = response.json()["run_id"]
    await agent.started.wait()
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
        found = await client.get("/api/chat/runs", params={"request_id": request_id})
        assert found.json()[0]["run_id"] == run_id
        assert len(agent.calls) == 1
        assert agent.deliveries == []
        agent.release.set()
        await _terminal(manager, run_id)
        assert agent.deliveries == []
        result = await client.get(f"/api/chat/runs/{run_id}")
        assert result.json()["status"] == "completed"
        await client.get(f"/api/chat/runs/{run_id}")
        assert agent.deliveries == [run_id]
        assert (await client.post(f"/api/chat/runs/{run_id}/stop")).json()["status"] == "completed"
        assert (await client.get("/api/chat/runs/missing")).status_code == 404
        assert (await client.post("/api/chat/runs/missing/stop")).status_code == 404
    await manager.stop_all()


async def test_busy_conversation_cannot_be_deleted() -> None:
    class Conversations:
        def __init__(self):
            self.exists = True

        async def get(self, _cid):
            return {"id": "conv"} if self.exists else None

        async def delete(self, _cid):
            self.exists = False

    agent = _Agent()
    coordinator = UserExecutionCoordinator()
    manager = ChatRunManager(agent, coordinator)
    conversations = Conversations()
    app = create_api_app(agent=agent, storage=SimpleNamespace(conversations=conversations))
    app.state.execution_coordinator = coordinator
    app.state.chat_runs = manager
    run = _submit(manager)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, client=("127.0.0.1", 12345)),
        base_url="http://127.0.0.1",
    ) as client:
        assert (await client.delete("/api/conversations/conv")).status_code == 409
        assert conversations.exists
        await manager.stop_all()
        assert (await client.delete("/api/conversations/conv")).status_code == 200
        assert not conversations.exists
        assert manager.list(conversation_id="conv") == []
        with pytest.raises(KeyError):
            manager.get(run["run_id"])
        with pytest.raises(ChatRunConflictError, match="expired"):
            _submit(manager, request_id=run["request_id"])


async def test_idempotency_fingerprint_distinguishes_message_and_conversation_boundaries() -> None:
    manager = ChatRunManager(_Agent(), UserExecutionCoordinator())
    request_id = str(uuid.uuid4())
    _submit(manager, message="c", conversation_id="a\0b", request_id=request_id)
    with pytest.raises(ChatRunConflictError):
        _submit(manager, message="b\0c", conversation_id="a", request_id=request_id)
    await manager.stop_all()


async def test_terminal_run_eviction_never_reexecutes_an_old_request() -> None:
    class ImmediateAgent:
        def __init__(self):
            self.calls = 0

        async def run_stream(self, *_args, **_kwargs):
            self.calls += 1
            yield StreamChunk(type="text", text="ok")
            yield StreamChunk(type="done")

    agent = ImmediateAgent()
    manager = ChatRunManager(agent, UserExecutionCoordinator())
    request_id = str(uuid.uuid4())
    first = _submit(manager, request_id=request_id)
    await _terminal(manager, first["run_id"])
    for _ in range(102):
        run = _submit(manager)
        await _terminal(manager, run["run_id"])
    with pytest.raises(KeyError):
        manager.get(first["run_id"])
    before = agent.calls
    with pytest.raises(ChatRunConflictError, match="expired"):
        _submit(manager, request_id=request_id)
    assert manager.stop_request(request_id) == {"request_id": request_id, "status": "expired"}
    assert manager.stop_request(request_id)["status"] == "expired"
    assert agent.calls == before
    await manager.stop_all()


async def test_concurrent_delivery_acknowledgements_do_not_duplicate_followup_effects() -> None:
    class DeliveryAgent(_Agent):
        def __init__(self):
            super().__init__()
            self.confirming = asyncio.Event()
            self.confirmed = asyncio.Event()

        async def confirm_delivery(self, _cid, _text, run_id):
            self.deliveries.append(run_id)
            self.confirming.set()
            await self.confirmed.wait()

    agent = DeliveryAgent()
    agent.release.set()
    manager = ChatRunManager(agent, UserExecutionCoordinator())
    run = _submit(manager)
    await _terminal(manager, run["run_id"])
    first = asyncio.create_task(manager.confirm_delivery(run["run_id"]))
    await agent.confirming.wait()
    await manager.confirm_delivery(run["run_id"])
    assert agent.deliveries == [run["run_id"]]
    agent.confirmed.set()
    await first
    await manager.stop_all()


async def test_older_running_snapshot_does_not_acknowledge_a_reply_completed_later() -> None:
    from fastapi import Request

    from src.api.routes.chat import get_chat_run

    agent = _Agent()
    manager = ChatRunManager(agent, UserExecutionCoordinator())
    app = create_api_app(agent=agent)
    app.state.chat_runs = manager
    run = _submit(manager)
    await agent.started.wait()
    scope = {"type": "http", "app": app}
    response = await get_chat_run(run["run_id"], Request(scope))
    agent.release.set()
    await _terminal(manager, run["run_id"])

    async def receive():
        return {"type": "http.request"}

    async def send(_event):
        return None

    await response(scope, receive, send)
    assert agent.deliveries == []
    terminal_response = await get_chat_run(run["run_id"], Request(scope))
    await terminal_response(scope, receive, send)
    assert agent.deliveries == [run["run_id"]]
    await manager.stop_all()


async def test_failed_http_send_does_not_acknowledge_terminal_delivery() -> None:
    from fastapi import Request

    from src.api.routes.chat import get_chat_run

    agent = _Agent()
    agent.release.set()
    manager = ChatRunManager(agent, UserExecutionCoordinator())
    app = create_api_app(agent=agent)
    app.state.chat_runs = manager
    run = _submit(manager)
    await _terminal(manager, run["run_id"])
    scope = {"type": "http", "app": app}
    response = await get_chat_run(run["run_id"], Request(scope))

    async def receive():
        return {"type": "http.request"}

    async def send(event):
        if event["type"] == "http.response.body":
            raise ConnectionError("synthetic client disconnect")

    with pytest.raises(ConnectionError):
        await response(scope, receive, send)
    assert agent.deliveries == []
    await manager.stop_all()


async def test_unknown_request_can_be_withdrawn_before_a_delayed_submission_is_accepted():
    agent = _Agent()
    manager = ChatRunManager(agent, UserExecutionCoordinator())
    app = create_api_app(agent=agent)
    app.state.chat_runs = manager
    request_id = str(uuid.uuid4())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, client=("127.0.0.1", 12345)),
        base_url="http://127.0.0.1",
    ) as client:
        assert (await client.get("/api/chat/runs", params={"request_id": request_id})).json() == []
        withdrawn = await client.post(f"/api/chat/requests/{request_id}/stop")
        assert withdrawn.status_code == 200
        assert withdrawn.json() == {"request_id": request_id, "status": "not_accepted"}
        repeated = await client.post(f"/api/chat/requests/{request_id}/stop")
        assert repeated.json() == withdrawn.json()
        late = await client.post(
            "/api/chat/runs", json={"message": "late", "request_id": request_id}
        )
        assert late.status_code == 409
        assert manager.list(request_id=request_id) == []
    assert agent.calls == []
    assert not manager.busy
    await manager.stop_all()


async def test_request_withdrawal_stops_an_already_accepted_run_and_is_idempotent():
    agent = _Agent()
    manager = ChatRunManager(agent, UserExecutionCoordinator())
    run = _submit(manager)
    await agent.started.wait()
    stopping = manager.stop_request(run["request_id"])
    assert stopping["run_id"] == run["run_id"]
    assert stopping["status"] == "stopping"
    assert manager.stop_request(run["request_id"])["status"] == "stopping"
    assert (await _terminal(manager, run["run_id"]))["status"] == "cancelled"
    assert manager.stop_request(run["request_id"])["status"] == "cancelled"
    with pytest.raises(ChatRunConflictError, match="withdrawn"):
        _submit(manager, request_id=run["request_id"])
    assert len(agent.calls) == 1
    await manager.stop_all()
