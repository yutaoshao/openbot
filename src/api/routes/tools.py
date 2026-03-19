"""Tool management routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from src.api.schemas import ToolConfigUpdateRequest, ToolStatusItem

router = APIRouter(prefix="/api/tools", tags=["tools"])


def _get_registry(request: Request):
    registry = getattr(request.app.state, "tool_registry", None)
    if registry is None:
        raise HTTPException(
            status_code=503,
            detail="Tool registry is not initialized for API requests.",
        )
    return registry


@router.get("", response_model=list[ToolStatusItem])
async def list_tools(request: Request) -> list[ToolStatusItem]:
    registry = _get_registry(request)
    return [ToolStatusItem(**item) for item in registry.list_status()]


@router.put("/{tool_name}/config", response_model=ToolStatusItem)
async def update_tool_config(
    tool_name: str,
    payload: ToolConfigUpdateRequest,
    request: Request,
) -> ToolStatusItem:
    registry = _get_registry(request)
    update_payload = {}
    if payload.enabled is not None:
        update_payload["enabled"] = payload.enabled
    if payload.config is not None:
        update_payload.update(payload.config)

    try:
        updated = registry.update_config(tool_name, update_payload)
    except KeyError as e:
        raise HTTPException(status_code=404, detail="Tool not found") from e
    return ToolStatusItem(**updated)
