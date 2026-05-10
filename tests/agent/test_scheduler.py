from __future__ import annotations

from typing import Any

from src.agent.scheduling import AgentScheduler


class _FakeScheduleRepo:
    def __init__(self) -> None:
        self.items = {
            "sched-1": {
                "id": "sched-1",
                "name": "wechat-push",
                "prompt": "hello",
                "cron": "0 8 * * *",
                "target_platform": "wechat",
                "target_id": "wechat:acc-1:user-1",
                "status": "active",
            },
        }
        self.created: dict[str, Any] | None = None

    async def create(
        self,
        *,
        name: str,
        prompt: str,
        cron: str,
        target_platform: str | None = None,
        target_id: str | None = None,
        status: str = "active",
        next_run_at: str | None = None,
    ) -> dict[str, Any]:
        item = {
            "id": "sched-2",
            "name": name,
            "prompt": prompt,
            "cron": cron,
            "target_platform": target_platform,
            "target_id": target_id,
            "status": status,
            "next_run_at": next_run_at,
        }
        self.created = item
        self.items[item["id"]] = item
        return item

    async def get(self, schedule_id: str) -> dict[str, Any] | None:
        return self.items.get(schedule_id)

    async def update(self, schedule_id: str, **fields: Any) -> dict[str, Any] | None:
        item = self.items.get(schedule_id)
        if item is None:
            return None
        item.update(fields)
        return item

    async def list_active(self) -> list[dict[str, Any]]:
        return list(self.items.values())


class _FakeStorage:
    def __init__(self) -> None:
        self.schedules = _FakeScheduleRepo()


class _FakeAgent:
    async def run(
        self,
        input_text: str,
        conversation_id: str = "",
        platform: str = "unknown",
        user_id: str = "",
    ) -> Any:
        return type("AgentResult", (), {"content": "scheduled reply", "latency_ms": 12})()


class _FakeEventBus:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    async def publish(self, event_name: str, data: dict[str, Any]) -> None:
        self.events.append((event_name, data))


class _FakeMsgHub:
    def get_adapter(self, platform: str) -> Any | None:
        raise AssertionError(
            f"wechat proactive send should be blocked before adapter lookup: {platform}"
        )


async def test_wechat_schedule_delivery_is_explicitly_blocked() -> None:
    event_bus = _FakeEventBus()
    scheduler = AgentScheduler(
        storage=_FakeStorage(),  # type: ignore[arg-type]
        agent=_FakeAgent(),  # type: ignore[arg-type]
        event_bus=event_bus,  # type: ignore[arg-type]
        msg_hub=_FakeMsgHub(),  # type: ignore[arg-type]
    )

    await scheduler._execute_schedule("sched-1")  # noqa: SLF001

    assert event_bus.events[-1] == (
        "scheduler.executed",
        {
            "schedule_id": "sched-1",
            "name": "wechat-push",
            "success": False,
        },
    )


async def test_create_schedule_rejects_wechat_target() -> None:
    storage = _FakeStorage()
    scheduler = AgentScheduler(
        storage=storage,  # type: ignore[arg-type]
        agent=_FakeAgent(),  # type: ignore[arg-type]
        event_bus=_FakeEventBus(),  # type: ignore[arg-type]
        msg_hub=_FakeMsgHub(),  # type: ignore[arg-type]
    )

    try:
        await scheduler.create_schedule(
            name="wechat-push",
            prompt="hello",
            cron="0 8 * * *",
            target_platform="wechat",
            target_id="wechat:acc-1:user-1",
        )
    except ValueError as exc:
        assert "微信当前只能在你发来消息后回复" in str(exc)
    else:
        raise AssertionError("Expected WeChat schedule creation to fail")

    assert storage.schedules.created is None


async def test_update_schedule_rejects_wechat_target() -> None:
    storage = _FakeStorage()
    storage.schedules.items["sched-2"] = {
        "id": "sched-2",
        "name": "telegram-push",
        "prompt": "hello",
        "cron": "0 8 * * *",
        "target_platform": "telegram",
        "target_id": "chat-123",
        "status": "active",
    }
    scheduler = AgentScheduler(
        storage=storage,  # type: ignore[arg-type]
        agent=_FakeAgent(),  # type: ignore[arg-type]
        event_bus=_FakeEventBus(),  # type: ignore[arg-type]
        msg_hub=_FakeMsgHub(),  # type: ignore[arg-type]
    )

    try:
        await scheduler.update_schedule(
            "sched-2",
            target_platform="wechat",
            target_id="wechat:acc-1:user-1",
        )
    except ValueError as exc:
        assert "微信当前只能在你发来消息后回复" in str(exc)
    else:
        raise AssertionError("Expected WeChat schedule update to fail")

    assert storage.schedules.items["sched-2"]["target_platform"] == "telegram"
