"""Cron trigger helpers for scheduled tasks."""

from __future__ import annotations

from datetime import UTC, datetime, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from apscheduler.triggers.cron import CronTrigger

from src.core.logging import get_logger

logger = get_logger(__name__)


def build_cron_trigger(cron_expr: str, timezone: tzinfo) -> CronTrigger:
    """Build a cron trigger in the scheduler timezone."""
    return CronTrigger.from_crontab(cron_expr, timezone=timezone)


def compute_next_run(cron_expr: str, timezone: tzinfo) -> str | None:
    """Compute the next fire time for a cron expression."""
    try:
        trigger = build_cron_trigger(cron_expr, timezone)
        next_fire = trigger.get_next_fire_time(None, datetime.now(timezone))
        return next_fire.isoformat() if next_fire else None
    except Exception:
        return None


def resolve_timezone(timezone_name: str) -> tzinfo:
    """Resolve configured timezone, falling back to the host local timezone."""
    if timezone_name:
        try:
            return ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError:
            logger.warning("scheduler.invalid_timezone", timezone=timezone_name)

    local_tz = datetime.now().astimezone().tzinfo
    return local_tz or UTC
