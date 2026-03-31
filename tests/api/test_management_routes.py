from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi.testclient import TestClient

from src.api.app import create_api_app
from src.core.config import AppConfig
from src.tools.registry import ToolRegistry, ToolResult


class _FakeKnowledgeRepo:
    def __init__(self) -> None:
        self.items: dict[str, dict[str, Any]] = {}

    async def list_all(
        self,
        category: str | None = None,
        priority: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        values = list(self.items.values())
        if category:
            values = [item for item in values if item["category"] == category]
        if priority:
            values = [item for item in values if item["priority"] == priority]
        return values[offset:offset + limit]

    async def search(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        return [item for item in self.items.values() if query in item["content"]][:limit]

    async def add(self, **kwargs: Any) -> None:
        item = {
            "id": kwargs["id"],
            "source_conversation_id": kwargs.get("source_conversation_id"),
            "category": kwargs["category"],
            "content": kwargs["content"],
            "tags": kwargs.get("tags"),
            "priority": kwargs.get("priority", "P1"),
            "confidence": kwargs.get("confidence"),
            "access_count": 0,
            "created_at": "2026-03-19T00:00:00Z",
            "updated_at": "2026-03-19T00:00:00Z",
            "expires_at": kwargs.get("expires_at"),
        }
        self.items[item["id"]] = item

    async def get(self, knowledge_id: str) -> dict[str, Any] | None:
        return self.items.get(knowledge_id)

    async def update(self, knowledge_id: str, **fields: Any) -> None:
        self.items[knowledge_id].update(fields)

    async def delete(self, knowledge_id: str) -> None:
        self.items.pop(knowledge_id, None)


class _FakeScheduleRepo:
    def __init__(self) -> None:
        self.items: dict[str, dict[str, Any]] = {}
        self._counter = 0

    async def list_all(
        self,
        *,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        values = list(self.items.values())
        if status:
            values = [item for item in values if item["status"] == status]
        return values[offset:offset + limit]

    async def create(self, **kwargs: Any) -> dict[str, Any]:
        self._counter += 1
        sid = f"s-{self._counter}"
        item = {
            "id": sid,
            "name": kwargs["name"],
            "prompt": kwargs["prompt"],
            "cron": kwargs["cron"],
            "target_platform": kwargs.get("target_platform"),
            "target_id": kwargs.get("target_id"),
            "status": kwargs.get("status", "active"),
            "last_run_at": None,
            "next_run_at": kwargs.get("next_run_at"),
            "created_at": "2026-03-19T00:00:00Z",
            "updated_at": "2026-03-19T00:00:00Z",
        }
        self.items[sid] = item
        return item

    async def get(self, schedule_id: str) -> dict[str, Any] | None:
        return self.items.get(schedule_id)

    async def update(self, schedule_id: str, **fields: Any) -> dict[str, Any] | None:
        if schedule_id not in self.items:
            return None
        self.items[schedule_id].update(fields)
        return self.items[schedule_id]

    async def delete(self, schedule_id: str) -> None:
        self.items.pop(schedule_id, None)


class _FakeConversationRepo:
    async def list_recent(self, limit: int = 20, offset: int = 0) -> list[dict]:
        return []

    async def search(self, query: str, limit: int = 10) -> list[dict]:
        return []

    async def get(self, conversation_id: str) -> dict | None:
        return None

    async def delete(self, conversation_id: str) -> None:
        return None


class _FakeMessageRepo:
    async def count_by_conversation(self, conversation_id: str) -> int:
        return 0

    async def get_by_conversation(
        self, conversation_id: str, limit: int | None = None, offset: int = 0
    ) -> list[dict]:
        return []


class _FakeStorage:
    def __init__(self) -> None:
        self.knowledge = _FakeKnowledgeRepo()
        self.schedules = _FakeScheduleRepo()
        self.conversations = _FakeConversationRepo()
        self.messages = _FakeMessageRepo()


class _FakeMonitor:
    async def get_overview(self, period: str = "today") -> dict:
        return {"period": period, "total_requests": 3, "error_rate": 0.0}

    async def get_latency(self, period: str = "7d") -> dict:
        return {"period": period, "p95": 123}

    async def get_tokens(self, period: str = "7d") -> dict:
        return {"period": period, "tokens_in": 10, "tokens_out": 20}

    async def get_tools(self, period: str = "7d") -> dict:
        return {"period": period, "tools": [{"tool": "file_manager", "count": 2}]}

    async def get_cost(self, period: str = "30d") -> dict:
        return {"period": period, "total_cost": 0.0123}


class _FakeRuntimeScheduler:
    def __init__(self, storage: _FakeStorage) -> None:
        self.storage = storage
        self.calls: list[tuple[str, Any]] = []
        self.timezone_name = "Asia/Shanghai"

    async def create_schedule(
        self,
        *,
        name: str,
        prompt: str,
        cron: str,
        target_platform: str | None = None,
        target_id: str | None = None,
        status: str = "active",
    ) -> dict[str, Any]:
        self.calls.append(("create", {"name": name, "cron": cron, "status": status}))
        return await self.storage.schedules.create(
            name=name,
            prompt=prompt,
            cron=cron,
            target_platform=target_platform,
            target_id=target_id,
            status=status,
            next_run_at="2026-03-29T08:00:00+08:00" if status == "active" else None,
        )

    async def update_schedule(self, schedule_id: str, **fields: Any) -> dict[str, Any] | None:
        self.calls.append(("update", {"id": schedule_id, "fields": fields}))
        return await self.storage.schedules.update(schedule_id, **fields)

    async def delete_schedule(self, schedule_id: str) -> None:
        self.calls.append(("delete", {"id": schedule_id}))
        await self.storage.schedules.delete(schedule_id)


@dataclass
class _DummyTool:
    name: str = "dummy"
    description: str = "dummy tool"
    category: str = "misc"
    parameters: dict[str, Any] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.parameters is None:
            self.parameters = {"type": "object", "properties": {}}

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        return ToolResult(content="ok")


def _client(
    *,
    storage: _FakeStorage | None = None,
    scheduler: Any | None = None,
) -> TestClient:
    storage = storage or _FakeStorage()
    registry = ToolRegistry()
    registry.register(_DummyTool())
    app = create_api_app(
        storage=storage,
        tool_registry=registry,
        monitor=_FakeMonitor(),
        config=AppConfig(),
        scheduler=scheduler,
    )
    return TestClient(app)


def test_knowledge_crud_and_search() -> None:
    client = _client()

    created = client.post(
        "/api/knowledge",
        json={"category": "fact", "content": "OpenBot uses FastAPI"},
    )
    assert created.status_code == 201
    knowledge_id = created.json()["id"]

    listed = client.get("/api/knowledge")
    assert listed.status_code == 200
    assert len(listed.json()) == 1

    searched = client.get("/api/knowledge/search?q=FastAPI")
    assert searched.status_code == 200
    assert searched.json()[0]["id"] == knowledge_id

    updated = client.put(f"/api/knowledge/{knowledge_id}", json={"priority": "P2"})
    assert updated.status_code == 200
    assert updated.json()["priority"] == "P2"

    deleted = client.delete(f"/api/knowledge/{knowledge_id}")
    assert deleted.status_code == 200


def test_tools_list_and_update() -> None:
    client = _client()

    listed = client.get("/api/tools")
    assert listed.status_code == 200
    assert listed.json()[0]["name"] == "dummy"

    updated = client.put(
        "/api/tools/dummy/config",
        json={"enabled": False, "config": {"x": 1}},
    )
    assert updated.status_code == 200
    assert updated.json()["enabled"] is False
    assert updated.json()["config"]["x"] == 1


def test_schedules_crud() -> None:
    client = _client()

    created = client.post(
        "/api/schedules",
        json={"name": "daily", "prompt": "summary", "cron": "0 8 * * *"},
    )
    assert created.status_code == 201
    schedule_id = created.json()["id"]

    listed = client.get("/api/schedules")
    assert listed.status_code == 200
    assert len(listed.json()) == 1

    updated = client.put(f"/api/schedules/{schedule_id}", json={"status": "paused"})
    assert updated.status_code == 200
    assert updated.json()["status"] == "paused"

    deleted = client.delete(f"/api/schedules/{schedule_id}")
    assert deleted.status_code == 200


def test_schedules_routes_sync_runtime_scheduler() -> None:
    storage = _FakeStorage()
    scheduler = _FakeRuntimeScheduler(storage)
    client = _client(storage=storage, scheduler=scheduler)

    created = client.post(
        "/api/schedules",
        json={"name": "daily", "prompt": "summary", "cron": "0 8 * * *"},
    )
    assert created.status_code == 201
    schedule_id = created.json()["id"]
    assert scheduler.calls[0][0] == "create"

    updated = client.put(f"/api/schedules/{schedule_id}", json={"status": "paused"})
    assert updated.status_code == 200
    assert scheduler.calls[1][0] == "update"

    deleted = client.delete(f"/api/schedules/{schedule_id}")
    assert deleted.status_code == 200
    assert scheduler.calls[2][0] == "delete"


def test_metrics_endpoints() -> None:
    client = _client()

    assert client.get("/api/metrics/overview?period=today").status_code == 200
    assert client.get("/api/metrics/latency?period=7d").status_code == 200
    assert client.get("/api/metrics/tokens?period=7d").status_code == 200
    assert client.get("/api/metrics/tools?period=7d").status_code == 200
    assert client.get("/api/metrics/cost?period=30d").status_code == 200


def test_settings_get_and_put() -> None:
    client = _client()

    current = client.get("/api/settings")
    assert current.status_code == 200
    assert current.json()["telegram"]["mode"] == "polling"

    updated = client.put("/api/settings", json={"telegram": {"enable_streaming": True}})
    assert updated.status_code == 200
    assert updated.json()["settings"]["telegram"]["enable_streaming"] is True
