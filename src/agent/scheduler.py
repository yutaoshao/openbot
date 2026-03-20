"""APScheduler-based task scheduler for the agent.

Manages scheduled tasks that trigger agent execution at specified intervals.
Tasks are persisted in the database and restored on startup.

Flow: Schedule fires -> Agent.run() -> result pushed to target platform.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from src.core.logging import get_logger

if TYPE_CHECKING:
    from src.agent.agent import Agent
    from src.channels.hub import MsgHub
    from src.infrastructure.event_bus import EventBus
    from src.infrastructure.storage import Storage

logger = get_logger(__name__)


class AgentScheduler:
    """Runs scheduled prompts through the Agent and delivers results.

    Each schedule row maps to an APScheduler CronTrigger job.  On startup
    all active schedules are loaded from the database and registered.
    The REST API can add/remove/pause schedules at runtime.
    """

    def __init__(
        self,
        storage: Storage,
        agent: Agent,
        event_bus: EventBus,
        msg_hub: MsgHub,
    ) -> None:
        self._storage = storage
        self._agent = agent
        self._event_bus = event_bus
        self._msg_hub = msg_hub
        self._scheduler = AsyncIOScheduler(timezone="UTC")

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Load active schedules from DB and start the scheduler."""
        active = await self._storage.schedules.list_active()
        for sched in active:
            self._add_job(sched)

        self._scheduler.start()
        logger.info("scheduler.started", active_jobs=len(active))

    async def stop(self) -> None:
        """Gracefully shut down the scheduler."""
        self._scheduler.shutdown(wait=False)
        logger.info("scheduler.stopped")

    # ------------------------------------------------------------------
    # Runtime management (called by REST API / Application)
    # ------------------------------------------------------------------

    async def add_schedule(
        self,
        name: str,
        prompt: str,
        cron: str,
        target_platform: str | None = None,
        target_id: str | None = None,
    ) -> dict[str, Any]:
        """Create a new schedule, persist it, and register the job."""
        next_run = self._compute_next_run(cron)
        sched = await self._storage.schedules.create(
            name=name,
            prompt=prompt,
            cron=cron,
            target_platform=target_platform,
            target_id=target_id,
            status="active",
            next_run_at=next_run,
        )
        self._add_job(sched)
        logger.info("scheduler.schedule_added", name=name, cron=cron)
        return sched

    async def remove_schedule(self, schedule_id: str) -> None:
        """Remove a schedule from DB and APScheduler."""
        job_id = f"schedule_{schedule_id}"
        if self._scheduler.get_job(job_id):
            self._scheduler.remove_job(job_id)
        await self._storage.schedules.delete(schedule_id)
        logger.info("scheduler.schedule_removed", schedule_id=schedule_id)

    async def pause_schedule(self, schedule_id: str) -> None:
        """Pause a schedule (set status to 'paused')."""
        job_id = f"schedule_{schedule_id}"
        if self._scheduler.get_job(job_id):
            self._scheduler.pause_job(job_id)
        await self._storage.schedules.update(schedule_id, status="paused")
        logger.info("scheduler.schedule_paused", schedule_id=schedule_id)

    async def resume_schedule(self, schedule_id: str) -> None:
        """Resume a paused schedule."""
        sched = await self._storage.schedules.get(schedule_id)
        if sched is None:
            return
        job_id = f"schedule_{schedule_id}"
        job = self._scheduler.get_job(job_id)
        if job:
            self._scheduler.resume_job(job_id)
        else:
            sched["status"] = "active"
            self._add_job(sched)
        await self._storage.schedules.update(schedule_id, status="active")
        logger.info("scheduler.schedule_resumed", schedule_id=schedule_id)


    async def _execute_schedule(self, schedule_id: str) -> None:
        """Called by APScheduler when a cron trigger fires."""
        sched = await self._storage.schedules.get(schedule_id)
        if sched is None or sched["status"] != "active":
            return

        prompt = sched["prompt"]
        target_platform = sched.get("target_platform")
        target_id = sched.get("target_id")

        logger.info(
            "scheduler.executing",
            schedule_id=schedule_id,
            name=sched["name"],
        )

        try:
            result = await self._agent.run(
                input_text=prompt,
                conversation_id=f"schedule_{schedule_id}",
                platform="scheduler",
            )

            # Deliver result to target platform if configured
            if target_platform and target_id:
                from src.channels.types import MessageContent

                adapter = self._msg_hub.get_adapter(target_platform)
                if adapter:
                    await adapter.send_message(
                        target_id,
                        MessageContent(text=result.content),
                    )

            # Update last_run and next_run
            now = datetime.now(UTC).isoformat()
            next_run = self._compute_next_run(sched["cron"])
            await self._storage.schedules.update(
                schedule_id,
                last_run_at=now,
                next_run_at=next_run,
            )

            await self._event_bus.publish("scheduler.executed", {
                "schedule_id": schedule_id,
                "name": sched["name"],
                "success": True,
                "content_preview": result.content[:200],
                "latency_ms": result.latency_ms,
            })

            logger.info(
                "scheduler.executed",
                schedule_id=schedule_id,
                latency_ms=result.latency_ms,
            )

        except Exception:
            logger.exception(
                "scheduler.execution_failed",
                schedule_id=schedule_id,
            )
            await self._event_bus.publish("scheduler.executed", {
                "schedule_id": schedule_id,
                "name": sched["name"],
                "success": False,
            })


    def _add_job(self, sched: dict[str, Any]) -> None:
        """Register an APScheduler job from a schedule dict."""
        job_id = f"schedule_{sched['id']}"

        # Remove existing job if any (for re-registration)
        if self._scheduler.get_job(job_id):
            self._scheduler.remove_job(job_id)

        trigger = CronTrigger.from_crontab(sched["cron"])
        self._scheduler.add_job(
            self._execute_schedule,
            trigger=trigger,
            id=job_id,
            args=[sched["id"]],
            name=sched.get("name", job_id),
            replace_existing=True,
        )

    @staticmethod
    def _compute_next_run(cron_expr: str) -> str | None:
        """Compute the next fire time for a cron expression."""
        try:
            trigger = CronTrigger.from_crontab(cron_expr)
            next_fire = trigger.get_next_fire_time(None, datetime.now(UTC))
            return next_fire.isoformat() if next_fire else None
        except Exception:
            return None
