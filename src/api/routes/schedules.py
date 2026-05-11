"""Schedule management routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

from src.agent.scheduling.delivery_policy import assert_supported_schedule_target
from src.api.schemas import ScheduleCreateRequest, ScheduleItem, ScheduleUpdateRequest

router = APIRouter(prefix="/api/schedules", tags=["schedules"])


def _get_storage(request: Request):
    storage = getattr(request.app.state, "storage", None)
    if storage is None:
        raise HTTPException(
            status_code=503,
            detail="Storage is not initialized for API requests.",
        )
    return storage


def _get_scheduler(request: Request):
    return getattr(request.app.state, "scheduler", None)


def _validate_schedule_target(
    target_platform: str | None,
    target_id: str | None,
) -> None:
    try:
        assert_supported_schedule_target(target_platform, target_id=target_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("", response_model=list[ScheduleItem])
async def list_schedules(
    request: Request,
    status: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[ScheduleItem]:
    storage = _get_storage(request)
    items = await storage.schedules.list_all(
        status=status,
        limit=limit,
        offset=offset,
    )
    return [ScheduleItem(**item) for item in items]


@router.post("", response_model=ScheduleItem, status_code=201)
async def create_schedule(
    payload: ScheduleCreateRequest,
    request: Request,
) -> ScheduleItem:
    storage = _get_storage(request)
    scheduler = _get_scheduler(request)
    _validate_schedule_target(payload.target_platform, payload.target_id)
    if scheduler is not None:
        item = await scheduler.create_schedule(
            name=payload.name,
            prompt=payload.prompt,
            cron=payload.cron,
            target_platform=payload.target_platform,
            target_id=payload.target_id,
            status=payload.status,
        )
    else:
        item = await storage.schedules.create(
            name=payload.name,
            prompt=payload.prompt,
            cron=payload.cron,
            target_platform=payload.target_platform,
            target_id=payload.target_id,
            status=payload.status,
            next_run_at=payload.next_run_at,
        )
    return ScheduleItem(**item)


@router.put("/{schedule_id}", response_model=ScheduleItem)
async def update_schedule(
    schedule_id: str,
    payload: ScheduleUpdateRequest,
    request: Request,
) -> ScheduleItem:
    storage = _get_storage(request)
    scheduler = _get_scheduler(request)
    existing = await storage.schedules.get(schedule_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Schedule not found")

    fields = payload.model_dump(exclude_none=True)
    _validate_schedule_target(
        fields.get("target_platform", existing.get("target_platform")),
        fields.get("target_id", existing.get("target_id")),
    )
    if scheduler is not None:
        updated = await scheduler.update_schedule(
            schedule_id,
            **fields,
        )
    else:
        updated = await storage.schedules.update(
            schedule_id,
            **fields,
        )
    if updated is None:
        raise HTTPException(status_code=500, detail="Failed to update schedule")
    return ScheduleItem(**updated)


@router.delete("/{schedule_id}")
async def delete_schedule(schedule_id: str, request: Request) -> dict[str, str]:
    storage = _get_storage(request)
    scheduler = _get_scheduler(request)
    existing = await storage.schedules.get(schedule_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Schedule not found")
    if scheduler is not None:
        await scheduler.delete_schedule(schedule_id)
    else:
        await storage.schedules.delete(schedule_id)
    return {"status": "deleted", "schedule_id": schedule_id}
