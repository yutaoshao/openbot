"""Schedule manager operation handlers."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.agent.scheduling.delivery_policy import (
    WECHAT_SCHEDULE_CREATE_UNSUPPORTED,
    WECHAT_SCHEDULE_UPDATE_UNSUPPORTED,
    is_wechat_delivery_target,
)
from src.tools.effects import EFFECT_NONE, STATUS_COMPLETED, STATUS_ERROR, tool_effect
from src.tools.registry import ToolResult
from src.tools.runtime import get_tool_execution_context

if TYPE_CHECKING:
    from src.agent.scheduling import AgentScheduler


async def create_schedule(scheduler: AgentScheduler, args: dict[str, Any]) -> ToolResult:
    name = (args.get("name") or "").strip()
    prompt = (args.get("prompt") or "").strip()
    cron = (args.get("cron") or "").strip()
    status = (args.get("status") or "active").strip() or "active"
    if not name or not prompt or not cron:
        return schedule_error(
            "name, prompt, and cron are required to create a schedule",
            "schedule.create",
        )

    target_platform, target_id = _schedule_target(args)
    if is_wechat_delivery_target(target_platform):
        return schedule_error(WECHAT_SCHEDULE_CREATE_UNSUPPORTED, "schedule.create")

    try:
        schedule = await scheduler.create_schedule(
            name=name,
            prompt=prompt,
            cron=cron,
            target_platform=target_platform,
            target_id=target_id,
            status=status,
        )
    except ValueError as exc:
        return schedule_error(str(exc), "schedule.create")
    return _schedule_success(
        _created_text(schedule, scheduler.timezone_name),
        "schedule.create",
        "schedule_created",
        str(schedule["id"]),
        schedule,
    )


async def list_schedules(scheduler: AgentScheduler, args: dict[str, Any]) -> ToolResult:
    limit = int(args.get("limit") or 20)
    items = await scheduler.list_schedules(status=args.get("list_status"), limit=limit)
    if not items:
        return _schedule_success("No schedules found.", "schedule.list", "schedule_listed")

    lines = [f"Scheduler timezone: {scheduler.timezone_name}"]
    for item in items:
        lines.append(
            f"- {item['id']}: {item['name']} "
            f"[{item['status']}] cron={item['cron']} "
            f"next_run={item.get('next_run_at') or '-'}"
        )
    return _schedule_success(
        "\n".join(lines),
        "schedule.list",
        "schedule_listed",
        metadata={"count": len(items)},
    )


async def update_schedule(scheduler: AgentScheduler, args: dict[str, Any]) -> ToolResult:
    schedule_id = (args.get("schedule_id") or "").strip()
    if not schedule_id:
        return schedule_error("schedule_id is required to update a schedule", "schedule.update")

    fields = _update_fields(args)
    if not fields:
        return schedule_error(
            "No schedule fields were provided to update.",
            "schedule.update",
            schedule_id,
        )
    if is_wechat_delivery_target(fields.get("target_platform")):
        return schedule_error(WECHAT_SCHEDULE_UPDATE_UNSUPPORTED, "schedule.update", schedule_id)

    try:
        updated = await scheduler.update_schedule(schedule_id, **fields)
    except ValueError as exc:
        return schedule_error(str(exc), "schedule.update", schedule_id)
    if updated is None:
        return schedule_error(f"Schedule not found: {schedule_id}", "schedule.update", schedule_id)
    return _schedule_success(
        _updated_text(updated),
        "schedule.update",
        "schedule_updated",
        str(updated["id"]),
        updated,
    )


async def delete_schedule(scheduler: AgentScheduler, args: dict[str, Any]) -> ToolResult:
    schedule_id = (args.get("schedule_id") or "").strip()
    if not schedule_id:
        return schedule_error("schedule_id is required to delete a schedule", "schedule.delete")
    existing = await scheduler.get_schedule(schedule_id)
    if existing is None:
        return schedule_error(f"Schedule not found: {schedule_id}", "schedule.delete", schedule_id)

    await scheduler.delete_schedule(schedule_id)
    return _schedule_success(
        f"Deleted schedule {schedule_id} ({existing['name']}).",
        "schedule.delete",
        "schedule_deleted",
        schedule_id,
        {"schedule_id": schedule_id},
    )


def schedule_error(content: str, action: str, target: str = "") -> ToolResult:
    return ToolResult(
        content=content,
        is_error=True,
        effects=(_schedule_effect(action, EFFECT_NONE, STATUS_ERROR, target),),
    )


def _schedule_success(
    content: str,
    action: str,
    effect: str,
    target: str = "",
    metadata: dict[str, Any] | None = None,
) -> ToolResult:
    return ToolResult(
        content=content,
        metadata=dict(metadata or {}),
        effects=(_schedule_effect(action, effect, STATUS_COMPLETED, target),),
    )


def _schedule_target(args: dict[str, Any]) -> tuple[Any, Any]:
    target_platform = args.get("target_platform")
    target_id = args.get("target_id")
    context = get_tool_execution_context()
    if context is not None and context.platform not in {"scheduler", "unknown"}:
        target_platform = target_platform or context.platform
        target_id = target_id or context.target_id
    return target_platform, target_id


def _update_fields(args: dict[str, Any]) -> dict[str, Any]:
    return {
        key: args[key]
        for key in ("name", "prompt", "cron", "status", "target_platform", "target_id")
        if key in args and args[key] is not None
    }


def _created_text(schedule: dict[str, Any], timezone_name: str) -> str:
    return (
        f"Created schedule {schedule['id']} named '{schedule['name']}' "
        f"with cron '{schedule['cron']}' in timezone {timezone_name}. "
        f"Status: {schedule['status']}. "
        f"Next run: {schedule.get('next_run_at') or 'not scheduled yet'}."
    )


def _updated_text(updated: dict[str, Any]) -> str:
    return (
        f"Updated schedule {updated['id']} to status {updated['status']}. "
        f"Cron: {updated['cron']}. "
        f"Next run: {updated.get('next_run_at') or 'not scheduled'}."
    )


def _schedule_effect(action: str, effect: str, status: str, target: str = ""):
    return tool_effect(
        action,
        effect,
        status=status,
        target_type="schedule",
        target=target,
        name="schedule_manager",
    )
