"""Schedule management tool for recurring tasks."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.tools.builtin.schedule_operations import (
    create_schedule,
    delete_schedule,
    list_schedules,
    schedule_error,
    update_schedule,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from src.agent.scheduling import AgentScheduler
    from src.tools.registry import ToolResult


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
            "Creates, inspects, updates, or deletes scheduled recurring tasks. "
            "Use when the user asks for reminders, recurring checks, delayed work, "
            f"or scheduled automation; cron expressions use {timezone_name}. "
            "Do not use when the user only wants an immediate answer, has not expressed "
            "a timing/schedule intent, or the requested follow-up cannot be represented "
            "as a recurring schedule. WeChat cannot receive scheduled results proactively; "
            "use Telegram for scheduled notifications."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": _parameter_properties(),
            "required": ["operation"],
        }

    @property
    def category(self) -> str:
        return "automation"

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        scheduler = self._scheduler_provider()
        if scheduler is None:
            return schedule_error("Scheduler is not available yet.", "schedule.list")

        operation = args.get("operation", "")
        handlers = {
            "create": create_schedule,
            "list": list_schedules,
            "update": update_schedule,
            "delete": delete_schedule,
        }
        handler = handlers.get(operation)
        if handler is None:
            return schedule_error(f"Unknown operation: {operation}", "schedule.list")
        return await handler(scheduler, args)


def _parameter_properties() -> dict[str, Any]:
    return {
        "operation": {
            "type": "string",
            "enum": ["create", "list", "update", "delete"],
            "description": "Schedule operation to perform",
        },
        "schedule_id": {
            "type": "string",
            "description": "Existing schedule id for update/delete operations",
        },
        "name": {"type": "string", "description": "Human-readable schedule name"},
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
    }
