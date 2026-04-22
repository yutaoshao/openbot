"""Metrics routes for dashboard/monitoring."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

router = APIRouter(prefix="/api/metrics", tags=["metrics"])


def _get_monitor(request: Request):
    monitor = getattr(request.app.state, "monitor", None)
    if monitor is None:
        raise HTTPException(
            status_code=503,
            detail="Metrics monitor is not initialized for API requests.",
        )
    return monitor


@router.get("/overview")
async def overview(
    request: Request,
    period: str = Query(default="today", pattern="^(today|7d|30d)$"),
) -> dict:
    return await _get_monitor(request).get_overview(period=period)


@router.get("/latency")
async def latency(
    request: Request,
    period: str = Query(default="7d", pattern="^(today|7d|30d)$"),
) -> dict:
    return await _get_monitor(request).get_latency(period=period)


@router.get("/tokens")
async def tokens(
    request: Request,
    period: str = Query(default="7d", pattern="^(today|7d|30d)$"),
) -> dict:
    return await _get_monitor(request).get_tokens(period=period)


@router.get("/tools")
async def tools(
    request: Request,
    period: str = Query(default="7d", pattern="^(today|7d|30d)$"),
) -> dict:
    return await _get_monitor(request).get_tools(period=period)


@router.get("/cost")
async def cost(
    request: Request,
    period: str = Query(default="30d", pattern="^(today|7d|30d)$"),
) -> dict:
    return await _get_monitor(request).get_cost(period=period)


@router.get("/harness")
async def harness(
    request: Request,
    period: str = Query(default="7d", pattern="^(today|7d|30d)$"),
) -> dict:
    return await _get_monitor(request).get_harness(period=period)
