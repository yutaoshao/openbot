"""Schedule management tool for recurring tasks."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.tools.registry import ToolResult
from src.tools.runtime import get_tool_execution_context

if TYPE_CHECKING:
    from collections.abc import Callable

    from src.agent.scheduling import AgentScheduler


class ScheduleManagerTool:
    """Create and manage recurring schedules."""

    def __init__(
        self,
        scheduler_provider: Callable[[], AgentScheduler | None],
    ) -> None:
        self._scheduler_provider = scheduler_provider

    @property
    def name(self) -> str:
        return "schedule_manager"

    @property
    def description(self) -> str:
        scheduler = self._scheduler_provider()
        timezone_name = (
            scheduler.timezone_name
            if scheduler is not None
            else "the scheduler's configured timezone"
        )
        return (
            "Create, inspect, update, pause, resume, or delete recurring tasks. "
            "Use this whenever the user asks you to do something later or on a recurring schedule. "
            f"Cron expressions use {timezone_name}. "
            "If target_platform and target_id are omitted during chat, "
            "the schedule will reply back to the current conversation when possible."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": ["create", "list", "update", "delete"],
                    "description": "Schedule operation to perform",
                },
                "schedule_id": {
                    "type": "string",
                    "description": "Existing schedule id for update/delete operations",
                },
                "name": {
                    "type": "string",
                    "description": "Human-readable schedule name",
                },
                "prompt": {
                    "type": "string",
                    "description": "Prompt that will be executed when the schedule fires",
                },
                "cron": {
                    "type": "string",
                    "description": "Five-field cron expression, such as '0 8 * * *'",
                },
                "status": {
                    "type": "string",
                    "enum": ["active", "paused"],
                    "description": "Desired schedule state",
                },
                "target_platform": {
                    "type": "string",
                    "description": "Optional delivery platform for scheduled results",
                },
                "target_id": {
                    "type": "string",
                    "description": "Optional delivery target id for scheduled results",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of schedules to return for list",
                    "default": 20,
                },
                "list_status": {
                    "type": "string",
                    "enum": ["active", "paused"],
                    "description": "Optional status filter for list",
                },
            },
            "required": ["operation"],
        }

    @property
    def category(self) -> str:
        return "automation"

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        scheduler = self._scheduler_provider()
        if scheduler is None:
            return ToolResult(content="Scheduler is not available yet.", is_error=True)

        operation = args.get("operation", "")
        handlers = {
            "create": self._create_schedule,
            "list": self._list_schedules,
            "update": self._update_schedule,
            "delete": self._delete_schedule,
        }
        handler = handlers.get(operation)
        if handler is None:
            return ToolResult(content=f"Unknown operation: {operation}", is_error=True)
        return await handler(scheduler, args)

    async def _create_schedule(
        self,
        scheduler: AgentScheduler,
        args: dict[str, Any],
    ) -> ToolResult:
        name = (args.get("name") or "").strip()
        prompt = (args.get("prompt") or "").strip()
        cron = (args.get("cron") or "").strip()
        status = (args.get("status") or "active").strip() or "active"

        if not name or not prompt or not cron:
            return ToolResult(
                content="name, prompt, and cron are required to create a schedule",
                is_error=True,
            )

        target_platform = args.get("target_platform")
        target_id = args.get("target_id")
        context = get_tool_execution_context()
        if context is not None and context.platform not in {"scheduler", "unknown"}:
            target_platform = target_platform or context.platform
            target_id = target_id or context.target_id

        schedule = await scheduler.create_schedule(
            name=name,
            prompt=prompt,
            cron=cron,
            target_platform=target_platform,
            target_id=target_id,
            status=status,
        )
        return ToolResult(
            content=(
                f"Created schedule {schedule['id']} named '{schedule['name']}' "
                f"with cron '{schedule['cron']}' in timezone {scheduler.timezone_name}. "
                f"Status: {schedule['status']}. "
                f"Next run: {schedule.get('next_run_at') or 'not scheduled yet'}."
            ),
            metadata=schedule,
        )

    async def _list_schedules(
        self,
        scheduler: AgentScheduler,
        args: dict[str, Any],
    ) -> ToolResult:
        limit = int(args.get("limit") or 20)
        status = args.get("list_status")
        items = await scheduler.list_schedules(status=status, limit=limit)
        if not items:
            return ToolResult(content="No schedules found.")

        lines = [f"Scheduler timezone: {scheduler.timezone_name}"]
        for item in items:
            lines.append(
                f"- {item['id']}: {item['name']} "
                f"[{item['status']}] cron={item['cron']} "
                f"next_run={item.get('next_run_at') or '-'}"
            )
        return ToolResult(content="\n".join(lines), metadata={"count": len(items)})

    async def _update_schedule(
        self,
        scheduler: AgentScheduler,
        args: dict[str, Any],
    ) -> ToolResult:
        schedule_id = (args.get("schedule_id") or "").strip()
        if not schedule_id:
            return ToolResult(content="schedule_id is required to update a schedule", is_error=True)

        fields = {
            key: args[key]
            for key in ("name", "prompt", "cron", "status", "target_platform", "target_id")
            if key in args and args[key] is not None
        }
        if not fields:
            return ToolResult(content="No schedule fields were provided to update.", is_error=True)

        updated = await scheduler.update_schedule(schedule_id, **fields)
        if updated is None:
            return ToolResult(content=f"Schedule not found: {schedule_id}", is_error=True)

        return ToolResult(
            content=(
                f"Updated schedule {updated['id']} to status {updated['status']}. "
                f"Cron: {updated['cron']}. "
                f"Next run: {updated.get('next_run_at') or 'not scheduled'}."
            ),
            metadata=updated,
        )

    async def _delete_schedule(
        self,
        scheduler: AgentScheduler,
        args: dict[str, Any],
    ) -> ToolResult:
        schedule_id = (args.get("schedule_id") or "").strip()
        if not schedule_id:
            return ToolResult(content="schedule_id is required to delete a schedule", is_error=True)

        existing = await scheduler.get_schedule(schedule_id)
        if existing is None:
            return ToolResult(content=f"Schedule not found: {schedule_id}", is_error=True)

        await scheduler.delete_schedule(schedule_id)
        return ToolResult(
            content=f"Deleted schedule {schedule_id} ({existing['name']}).",
            metadata={"schedule_id": schedule_id},
        )
