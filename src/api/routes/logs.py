"""Logs API routes for querying structured agent logs."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

router = APIRouter(prefix="/api/logs", tags=["logs"])


def _get_storage(request: Request):
    storage = getattr(request.app.state, "storage", None)
    if storage is None:
        raise HTTPException(status_code=503, detail="Storage not initialized")
    return storage


@router.get("")
async def list_logs(
    request: Request,
    trace_id: str | None = Query(default=None),
    interaction_id: str | None = Query(default=None),
    platform: str | None = Query(default=None),
    surface: str | None = Query(default=None),
    level: str | None = Query(default=None),
    event: str | None = Query(default=None),
    since: str | None = Query(default=None),
    until: str | None = Query(default=None),
    limit: int = Query(default=100, le=500),
    offset: int = Query(default=0),
) -> list[dict]:
    """Query structured logs with optional filters."""
    storage = _get_storage(request)
    return await storage.logs.query(
        trace_id=trace_id,
        interaction_id=interaction_id,
        platform=platform,
        surface=surface,
        level=level,
        event=event,
        since=since,
        until=until,
        limit=limit,
        offset=offset,
    )


@router.get("/stats")
async def log_stats(
    request: Request,
    since: str | None = Query(default=None),
    platform: str | None = Query(default=None),
) -> dict:
    """Get log count statistics by surface and level."""
    storage = _get_storage(request)
    total = await storage.logs.count(since=since, platform=platform)
    cognitive = await storage.logs.count(since=since, platform=platform, surface="cognitive")
    operational = await storage.logs.count(since=since, platform=platform, surface="operational")
    contextual = await storage.logs.count(since=since, platform=platform, surface="contextual")
    errors = await storage.logs.count(since=since, platform=platform, level="error")
    warnings = await storage.logs.count(since=since, platform=platform, level="warning")
    return {
        "total": total,
        "by_surface": {
            "cognitive": cognitive,
            "operational": operational,
            "contextual": contextual,
        },
        "by_level": {
            "error": errors,
            "warning": warnings,
            "info": total - errors - warnings,
        },
    }
