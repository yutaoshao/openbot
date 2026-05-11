from __future__ import annotations

from typing import Any

from src.agent.scheduling.delivery_policy import assert_supported_schedule_target
from src.tools.builtin.schedule_manager import ScheduleManagerTool
from src.tools.runtime import ToolExecutionContext, tool_execution_context


class _FakeScheduler:
    def __init__(self) -> None:
        self.timezone_name = "Asia/Shanghai"
        self.created: dict[str, Any] | None = None
        self.items: dict[str, dict[str, Any]] = {}

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
        assert_supported_schedule_target(target_platform, target_id=target_id)
        item = {
            "id": "sched-1",
            "name": name,
            "prompt": prompt,
            "cron": cron,
            "target_platform": target_platform,
            "target_id": target_id,
            "status": status,
            "next_run_at": "2026-03-29T08:00:00+08:00" if status == "active" else None,
        }
        self.created = item
        self.items[item["id"]] = item
        return item

    async def list_schedules(
        self,
        *,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        items = list(self.items.values())
        if status:
            items = [item for item in items if item["status"] == status]
        return items[offset : offset + limit]

    async def get_schedule(self, schedule_id: str) -> dict[str, Any] | None:
        return self.items.get(schedule_id)

    async def update_schedule(self, schedule_id: str, **fields: Any) -> dict[str, Any] | None:
        item = self.items.get(schedule_id)
        if item is None:
            return None
        target_platform = fields.get("target_platform", item.get("target_platform"))
        target_id = fields.get("target_id", item.get("target_id"))
        assert_supported_schedule_target(target_platform, target_id=target_id)
        item.update(fields)
        return item

    async def delete_schedule(self, schedule_id: str) -> None:
        self.items.pop(schedule_id, None)


async def test_create_schedule_uses_current_conversation_as_default_target() -> None:
    scheduler = _FakeScheduler()
    tool = ScheduleManagerTool(lambda: scheduler)

    with tool_execution_context(
        ToolExecutionContext(conversation_id="8058699462", platform="telegram")
    ):
        result = await tool.execute(
            {
                "operation": "create",
                "name": "Daily review",
                "prompt": "Check the codebase and report issues",
                "cron": "0 8 * * *",
            }
        )

    assert not result.is_error
    assert scheduler.created is not None
    assert scheduler.created["target_platform"] == "telegram"
    assert scheduler.created["target_id"] == "8058699462"
    assert "Asia/Shanghai" in result.content


async def test_create_schedule_rejects_wechat_default_target() -> None:
    scheduler = _FakeScheduler()
    tool = ScheduleManagerTool(lambda: scheduler)

    with tool_execution_context(
        ToolExecutionContext(conversation_id="wechat:acc-1:user-1", platform="wechat")
    ):
        result = await tool.execute(
            {
                "operation": "create",
                "name": "Daily diary",
                "prompt": "Write a diary entry",
                "cron": "0 1 * * *",
            }
        )

    assert result.is_error
    assert scheduler.created is None
    assert "微信当前只能在你发来消息后回复" in result.content
    assert "Telegram" in result.content


async def test_create_schedule_rejects_explicit_wechat_target() -> None:
    scheduler = _FakeScheduler()
    tool = ScheduleManagerTool(lambda: scheduler)

    result = await tool.execute(
        {
            "operation": "create",
            "name": "Daily diary",
            "prompt": "Write a diary entry",
            "cron": "0 1 * * *",
            "target_platform": "wechat",
            "target_id": "wechat:acc-1:user-1",
        }
    )

    assert result.is_error
    assert scheduler.created is None
    assert "不能主动推送定时任务结果" in result.content


async def test_create_schedule_rejects_invalid_explicit_telegram_target_id() -> None:
    scheduler = _FakeScheduler()
    tool = ScheduleManagerTool(lambda: scheduler)

    with tool_execution_context(
        ToolExecutionContext(conversation_id="8058699462", platform="telegram")
    ):
        result = await tool.execute(
            {
                "operation": "create",
                "name": "Daily diary",
                "prompt": "Write a diary entry",
                "cron": "0 1 * * *",
                "target_platform": "telegram",
                "target_id": "telegram",
            }
        )

    assert result.is_error
    assert scheduler.created is None
    assert "Telegram target_id" in result.content


async def test_update_schedule_rejects_wechat_target() -> None:
    scheduler = _FakeScheduler()
    tool = ScheduleManagerTool(lambda: scheduler)
    await scheduler.create_schedule(
        name="Daily review",
        prompt="Check the codebase and report issues",
        cron="0 8 * * *",
        target_platform="telegram",
        target_id="8058699462",
    )

    result = await tool.execute(
        {
            "operation": "update",
            "schedule_id": "sched-1",
            "target_platform": "wechat",
            "target_id": "wechat:acc-1:user-1",
        }
    )

    assert result.is_error
    assert scheduler.items["sched-1"]["target_platform"] == "telegram"
    assert "这个定时任务没有更新" in result.content


async def test_list_schedule_reports_timezone() -> None:
    scheduler = _FakeScheduler()
    tool = ScheduleManagerTool(lambda: scheduler)
    await scheduler.create_schedule(
        name="Daily review",
        prompt="Check the codebase and report issues",
        cron="0 8 * * *",
        status="active",
    )

    result = await tool.execute({"operation": "list"})

    assert not result.is_error
    assert "Scheduler timezone: Asia/Shanghai" in result.content
    assert "Daily review" in result.content
