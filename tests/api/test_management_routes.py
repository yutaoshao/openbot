from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from src.api.app import create_api_app
from src.application.settings import SettingsService
from src.core.config import AppConfig, WeChatConfig, load_config
from src.core.user_scope import SINGLE_USER_ID
from src.tools.registry import ToolRegistry, ToolResult

if TYPE_CHECKING:
    from pathlib import Path


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
        return values[offset : offset + limit]

    async def search(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        return [item for item in self.items.values() if query in item["content"]][:limit]

    async def add(self, **kwargs: Any) -> None:
        item = {
            "id": kwargs["id"],
            "user_id": kwargs.get("user_id", ""),
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
        return values[offset : offset + limit]

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

    async def get_cost(self, period: str = "30d") -> dict:
        return {"period": period, "total_cost_usd": 1.23, "daily": []}

    async def get_tools(self, period: str = "7d") -> dict:
        return {"period": period, "tools": [{"tool": "file_manager", "count": 2}]}

    async def get_harness(self, period: str = "7d") -> dict:
        return {
            "period": period,
            "queue_wait_avg_ms": 5,
            "queue_wait_p95_ms": 9,
            "serialized_requests": 3,
            "tool_activation_events": 1,
            "completion_rewrites": 1,
        }


class _FakeIdentityService:
    def __init__(self) -> None:
        self.items: dict[tuple[str, str], dict[str, str]] = {}

    async def list_identities(
        self,
        *,
        user_id: str | None = None,
        platform: str | None = None,
    ) -> list[dict[str, str]]:
        values = list(self.items.values())
        if user_id is not None:
            values = [item for item in values if item["user_id"] == user_id]
        if platform is not None:
            values = [item for item in values if item["platform"] == platform]
        return values

    async def bind_identity(
        self,
        *,
        user_id: str | None = None,
        platform: str,
        platform_user_id: str,
    ) -> dict[str, str]:
        if user_id and user_id != SINGLE_USER_ID:
            raise ValueError(
                "OpenBot runs in local single-user mode; only local-single-user is supported.",
            )
        item = {
            "id": f"{platform}-{platform_user_id}",
            "user_id": SINGLE_USER_ID,
            "platform": platform,
            "platform_user_id": platform_user_id,
            "created_at": "2026-03-19T00:00:00Z",
            "updated_at": "2026-03-19T00:00:00Z",
        }
        self.items[(platform, platform_user_id)] = item
        return item


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


class _FakeApplication:
    def __init__(self) -> None:
        self.restart_calls = 0

    async def request_restart(self, delay: float = 0.2) -> None:
        self.restart_calls += 1


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
    identity_service: _FakeIdentityService | None = None,
    config: AppConfig | None = None,
    settings_service: SettingsService | None = None,
    client_host: str = "127.0.0.1",
    application: Any | None = None,
) -> TestClient:
    storage = storage or _FakeStorage()
    registry = ToolRegistry()
    registry.register(_DummyTool())
    config = config or AppConfig()
    app = create_api_app(
        storage=storage,
        tool_registry=registry,
        monitor=_FakeMonitor(),
        config=config,
        scheduler=scheduler,
        identity_service=identity_service,
        settings_service=settings_service,
        application=application,
    )
    return TestClient(app, client=(client_host, 50000))


def _write_config_file(config_path: Path) -> None:
    config_path.write_text(
        """# test config
model:
  primary:
    provider: anthropic
    model: claude-test
    api_key_env: ANTHROPIC_API_KEY
    pricing_input: 0.6
    pricing_output: 1.2
  max_retries: 3
telegram:
  enabled: true
  mode: polling
  enable_streaming: false
agent:
  max_task_cost: 5
""",
        encoding="utf-8",
    )


def test_knowledge_crud_and_search() -> None:
    storage = _FakeStorage()
    client = _client(storage=storage)

    created = client.post(
        "/api/knowledge",
        json={"category": "fact", "content": "OpenBot uses FastAPI"},
    )
    assert created.status_code == 201
    knowledge_id = created.json()["id"]
    assert storage.knowledge.items[knowledge_id]["user_id"] == SINGLE_USER_ID

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
    assert client.get("/api/metrics/harness?period=7d").status_code == 200


def test_settings_get_and_put(monkeypatch: Any, tmp_path: Path) -> None:
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("FEISHU_APP_ID", raising=False)
    monkeypatch.delenv("FEISHU_APP_SECRET", raising=False)
    monkeypatch.delenv("FEISHU_VERIFICATION_TOKEN", raising=False)
    monkeypatch.delenv("FEISHU_ENCRYPT_KEY", raising=False)
    config_path = tmp_path / "config.yaml"
    _write_config_file(config_path)
    config = load_config(str(config_path))
    client = _client(
        config=config,
        settings_service=SettingsService(str(config_path)),
    )

    current = client.get("/api/settings")
    assert current.status_code == 200
    assert current.json()["telegram"]["enabled"] is True
    assert current.json()["telegram"]["mode"] == "polling"
    assert current.json()["api"]["local_only"] is True
    assert current.json()["restart_required"] is False
    assert current.json()["runtime"]["feishu"]["status"] == "disabled"
    telegram_runtime_status = current.json()["runtime"]["telegram"]["status"]
    assert telegram_runtime_status in {"incomplete", "starting"}
    assert current.json()["runtime"]["wechat"]["status"] == "disabled"

    updated = client.put(
        "/api/settings",
        json={
            "telegram": {"enabled": False, "enable_streaming": True},
            "model": {"max_retries": 5},
        },
    )
    assert updated.status_code == 200
    assert updated.json()["settings"]["telegram"]["enabled"] is False
    assert updated.json()["settings"]["telegram"]["enable_streaming"] is True
    assert updated.json()["settings"]["model"]["max_retries"] == 5
    assert updated.json()["restart_required"] is True
    assert updated.json()["restart_reasons"] == ["telegram", "model"]
    assert updated.json()["runtime"]["telegram"]["status"] == telegram_runtime_status

    reloaded = client.get("/api/settings")
    assert reloaded.status_code == 200
    assert reloaded.json()["telegram"]["enabled"] is False
    assert reloaded.json()["model"]["max_retries"] == 5
    assert reloaded.json()["restart_required"] is True
    assert reloaded.json()["restart_reasons"] == ["telegram", "model"]
    assert reloaded.json()["runtime"]["telegram"]["status"] == telegram_runtime_status

    persisted = config_path.read_text(encoding="utf-8")
    assert "# test config" in persisted
    assert "enable_streaming: true" in persisted
    assert "max_retries: 5" in persisted
    assert "pricing_input: 0.6" in persisted
    assert "max_task_cost: 5" in persisted


def test_settings_put_rejects_invalid_patch_without_mutating_file(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    _write_config_file(config_path)
    original = config_path.read_text(encoding="utf-8")
    config = load_config(str(config_path))
    client = _client(
        config=config,
        settings_service=SettingsService(str(config_path)),
    )

    response = client.put(
        "/api/settings",
        json={"telegram": {"bot_token_env": "SHOULD_NOT_BE_ALLOWED"}},
    )

    assert response.status_code == 400
    assert config_path.read_text(encoding="utf-8") == original


def test_settings_secrets_return_current_env_values(monkeypatch: Any, tmp_path: Path) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-secret-primary")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:telegram-token")
    config_path = tmp_path / "config.yaml"
    _write_config_file(config_path)
    config = load_config(str(config_path))
    client = _client(
        config=config,
        settings_service=SettingsService(str(config_path)),
    )

    response = client.get("/api/settings/secrets")

    assert response.status_code == 200
    secrets = {item["env_name"]: item for item in response.json()["secrets"]}
    assert secrets["ANTHROPIC_API_KEY"]["value"] == "sk-secret-primary"
    assert secrets["ANTHROPIC_API_KEY"]["is_set"] is True
    assert secrets["TELEGRAM_BOT_TOKEN"]["value"] == "123:telegram-token"


def test_settings_apply_requests_local_restart(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    _write_config_file(config_path)
    config = load_config(str(config_path))
    application = _FakeApplication()
    client = _client(
        config=config,
        settings_service=SettingsService(str(config_path)),
        application=application,
    )

    client.put(
        "/api/settings",
        json={
            "telegram": {"enabled": False},
        },
    )
    response = client.post("/api/settings/apply", json={})

    assert response.status_code == 200
    assert response.json()["status"] == "restarting"
    assert response.json()["restart_required"] is True
    assert response.json()["restart_reasons"] == ["telegram"]
    assert application.restart_calls == 1


def test_settings_reports_wechat_login_required_when_enabled_without_state(tmp_path) -> None:
    client = _client(
        config=AppConfig(
            wechat=WeChatConfig(
                enabled=True,
                state_path=str(tmp_path / "missing-ilink-state.json"),
            ),
        ),
    )

    current = client.get("/api/settings")

    assert current.status_code == 200
    assert current.json()["runtime"]["wechat"]["status"] == "login_required"


def test_local_only_blocks_remote_management_http() -> None:
    client = _client(client_host="203.0.113.10")

    response = client.get("/api/tools")

    assert response.status_code == 403
    assert "local access" in response.json()["detail"]


def test_local_only_allows_remote_webhook_requests() -> None:
    client = _client(client_host="203.0.113.10")

    response = client.post("/webhook/telegram", json={"message": "hello"})

    assert response.status_code == 503


def test_local_only_blocks_remote_websocket() -> None:
    client = _client(client_host="203.0.113.10")

    with pytest.raises(WebSocketDisconnect) as exc_info, client.websocket_connect("/api/ws/chat"):
        pass

    assert exc_info.value.code == 1008


def test_identity_routes_bind_and_list() -> None:
    identity_service = _FakeIdentityService()
    client = _client(identity_service=identity_service)

    bound = client.post(
        "/api/identities/bind",
        json={
            "platform": "telegram",
            "platform_user_id": "12345",
        },
    )
    assert bound.status_code == 200
    assert bound.json()["user_id"] == SINGLE_USER_ID

    listed = client.get("/api/identities?platform=telegram")
    assert listed.status_code == 200
    assert listed.json() == [bound.json()]


def test_identity_routes_reject_non_single_user_binding() -> None:
    identity_service = _FakeIdentityService()
    client = _client(identity_service=identity_service)

    response = client.post(
        "/api/identities/bind",
        json={
            "user_id": "user-1",
            "platform": "telegram",
            "platform_user_id": "12345",
        },
    )

    assert response.status_code == 400
    assert "single-user mode" in response.json()["detail"]
