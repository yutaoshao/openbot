"""Metrics collection and aggregation for management dashboard."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from statistics import mean
from typing import TYPE_CHECKING, Any

from src.core.logging import get_logger
from src.core.monitor_tokens import aggregate_token_events

if TYPE_CHECKING:
    from src.infrastructure.event_bus import EventBus
    from src.infrastructure.storage import Storage

logger = get_logger(__name__)


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    raw = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def _percentile(values: list[int], p: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    idx = max(0, min(len(ordered) - 1, int((len(ordered) - 1) * p)))
    return ordered[idx]


class MetricsCollector:
    """Collects runtime events and provides aggregate metric views."""

    def __init__(
        self,
        storage: Storage,
        event_bus: EventBus,
    ) -> None:
        self.storage = storage
        self.event_bus = event_bus
        self._subscribe()

    def _subscribe(self) -> None:
        self.event_bus.subscribe("agent.response", self._record_agent_response)
        self.event_bus.subscribe("agent.metrics", self._record_agent_metrics)
        self.event_bus.subscribe("agent.think.complete", self._record_think_complete)
        self.event_bus.subscribe("agent.tool.executed", self._record_tool_event)
        self.event_bus.subscribe("harness.completion_verified", self._record_completion_verified)
        self.event_bus.subscribe("harness.queue_wait", self._record_queue_wait)
        self.event_bus.subscribe("harness.tool_activated", self._record_tool_activation)
        self.event_bus.subscribe("model.request", self._record_model_request)
        self.event_bus.subscribe("app.agent_error", self._record_error_event)

    async def _record(self, event_name: str, data: dict[str, Any]) -> None:
        await self.storage.metrics.record(event_name, data)

    async def _record_agent_response(self, data: dict[str, Any]) -> None:
        await self._record("agent.response", data)

    async def _record_agent_metrics(self, data: dict[str, Any]) -> None:
        await self._record("agent.metrics", data)

    async def _record_think_complete(self, data: dict[str, Any]) -> None:
        await self._record("agent.think.complete", data)

    async def _record_tool_event(self, data: dict[str, Any]) -> None:
        await self._record("agent.tool.executed", data)

    async def _record_completion_verified(self, data: dict[str, Any]) -> None:
        await self._record("harness.completion_verified", data)

    async def _record_queue_wait(self, data: dict[str, Any]) -> None:
        await self._record("harness.queue_wait", data)

    async def _record_tool_activation(self, data: dict[str, Any]) -> None:
        await self._record("harness.tool_activated", data)

    async def _record_model_request(self, data: dict[str, Any]) -> None:
        await self._record("model.request", data)

    async def _record_error_event(self, data: dict[str, Any]) -> None:
        await self._record("app.agent_error", data)

    def _period_start(self, period: str) -> datetime:
        now = datetime.now(UTC)
        if period == "today":
            return datetime(now.year, now.month, now.day, tzinfo=UTC)
        if period == "7d":
            return now - timedelta(days=7)
        if period == "30d":
            return now - timedelta(days=30)
        return now - timedelta(days=7)

    async def _query_period(
        self,
        *,
        period: str,
        event_name: str | None = None,
        limit: int = 5000,
    ) -> list[dict[str, Any]]:
        start = self._period_start(period).isoformat()
        return await self.storage.metrics.query(
            event_name=event_name,
            start=start,
            limit=limit,
        )

    async def get_overview(self, period: str = "today") -> dict[str, Any]:
        start = self._period_start(period).isoformat()
        grouped = await self.storage.metrics.query_multi(
            event_names=[
                "agent.response",
                "agent.metrics",
                "agent.think.complete",
                "model.request",
                "app.agent_error",
            ],
            start=start,
        )
        response_events = grouped.get("agent.response", [])
        stream_events = grouped.get("agent.metrics", [])
        think_events = grouped.get("agent.think.complete", [])
        model_events = grouped.get("model.request", [])
        error_events = grouped.get("app.agent_error", [])

        total_requests = len(response_events) + len(stream_events)
        if think_events:
            total_requests = max(total_requests, len(think_events))
        success_count = max(0, total_requests - len(error_events))
        error_count = len(error_events)
        error_rate = (error_count / total_requests) if total_requests else 0.0
        success_rate = 1.0 - error_rate if total_requests else 0.0

        iterations = [
            int((item.get("data") or {}).get("iterations") or 0)
            for item in think_events
            if isinstance((item.get("data") or {}).get("iterations"), int)
        ]
        avg_steps = float(mean(iterations)) if iterations else 0.0

        return {
            "period": period,
            "total_requests": total_requests,
            "success_count": success_count,
            "error_count": error_count,
            "error_rate": error_rate,
            "success_rate": success_rate,
            "avg_steps": avg_steps,
            "avg_turns": avg_steps,
            "llm_api_calls": len(model_events),
            "avg_llm_api_calls": (len(model_events) / total_requests) if total_requests else 0.0,
        }

    async def get_latency(self, period: str = "7d") -> dict[str, Any]:
        response_events = await self._query_period(period=period, event_name="agent.response")
        stream_events = await self._query_period(period=period, event_name="agent.metrics")

        latencies: list[int] = []
        by_day: dict[str, list[int]] = defaultdict(list)
        for item in response_events + stream_events:
            data = item.get("data") or {}
            value = data.get("latency_ms")
            if isinstance(value, int):
                latencies.append(value)
                ts = _parse_iso(item.get("timestamp"))
                day = ts.date().isoformat() if ts else "unknown"
                by_day[day].append(value)

        daily = [
            {
                "date": day,
                "count": len(values),
                "avg": int(mean(values)) if values else 0,
                "p50": _percentile(values, 0.50),
                "p95": _percentile(values, 0.95),
            }
            for day, values in sorted(by_day.items(), key=lambda x: x[0])
        ]

        return {
            "period": period,
            "count": len(latencies),
            "avg_response_time": int(mean(latencies)) if latencies else 0,
            "ttft": _percentile(latencies, 0.50),
            "p50": _percentile(latencies, 0.50),
            "p95": _percentile(latencies, 0.95),
            "p99": _percentile(latencies, 0.99),
            "daily": daily,
        }

    async def get_tokens(self, period: str = "7d") -> dict[str, Any]:
        events = await self._query_period(period=period, event_name="model.request")
        return aggregate_token_events(events, period)

    async def get_cost(self, period: str = "30d") -> dict[str, Any]:
        events = await self._query_period(period=period, event_name="model.request")
        total_cost = 0.0
        daily: dict[str, float] = defaultdict(float)

        for item in events:
            data = item.get("data") or {}
            cost_usd = float(data.get("cost_usd") or 0.0)
            total_cost += cost_usd
            ts = _parse_iso(item.get("timestamp"))
            day = ts.date().isoformat() if ts else "unknown"
            daily[day] += cost_usd

        return {
            "period": period,
            "total_cost_usd": round(total_cost, 6),
            "avg_cost_usd_per_request": (total_cost / len(events)) if events else 0.0,
            "daily": [
                {"date": date, "cost_usd": round(value, 6)}
                for date, value in sorted(daily.items(), key=lambda x: x[0])
            ],
        }

    async def get_tools(self, period: str = "7d") -> dict[str, Any]:
        events = await self._query_period(period=period, event_name="agent.tool.executed")
        grouped: dict[str, dict[str, Any]] = defaultdict(
            lambda: {"tool": "", "count": 0, "error_count": 0}
        )

        for item in events:
            data = item.get("data") or {}
            tool = str(data.get("tool") or "unknown")
            grouped[tool]["tool"] = tool
            grouped[tool]["count"] += 1
            if bool(data.get("is_error")):
                grouped[tool]["error_count"] += 1

        rows = []
        for row in grouped.values():
            count = row["count"]
            error_count = row["error_count"]
            row["error_rate"] = (error_count / count) if count else 0.0
            rows.append(row)

        rows.sort(key=lambda item: item["count"], reverse=True)
        return {"period": period, "tools": rows}

    async def get_harness(self, period: str = "7d") -> dict[str, Any]:
        """Return runtime metrics for harness-specific behaviors."""
        start = self._period_start(period).isoformat()
        grouped = await self.storage.metrics.query_multi(
            event_names=[
                "harness.queue_wait",
                "harness.tool_activated",
                "harness.completion_verified",
            ],
            start=start,
        )
        queue_events = grouped.get("harness.queue_wait", [])
        queue_waits = [
            int((item.get("data") or {}).get("queue_wait_ms") or 0) for item in queue_events
        ]
        activated = grouped.get("harness.tool_activated", [])
        verified = grouped.get("harness.completion_verified", [])
        return {
            "period": period,
            "queue_wait_avg_ms": int(mean(queue_waits)) if queue_waits else 0,
            "queue_wait_p95_ms": _percentile(queue_waits, 0.95),
            "serialized_requests": len(queue_events),
            "tool_activation_events": len(activated),
            "completion_rewrites": len(verified),
        }
