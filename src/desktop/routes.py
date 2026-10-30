"""Desktop setup and explicit tool grants; all routes use instance authentication."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Annotated, Any, Literal

from fastapi import APIRouter, Body, HTTPException, Request
from pydantic import BaseModel, ConfigDict, ValidationError

from src.desktop.service import is_busy, pause_for_restart
from src.desktop.settings import EXECUTION_TOOLS

if TYPE_CHECKING:
    from src.desktop.service import DesktopService

router = APIRouter(prefix="/api/desktop", tags=["desktop"])


def _service(request: Request) -> DesktopService:
    return request.app.state.desktop_service


def _import_result(service: DesktopService) -> dict[str, str] | None:
    path = service.settings.data_dir / "import-result.json"
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if value.get("status") in {"imported", "failed_restored"}:
            return {"status": value["status"]}
    except (OSError, ValueError, AttributeError):
        pass
    return {"status": "unknown"}


@router.post("/browser-session")
async def browser_session() -> dict[str, str]:
    # The guard validated the in-memory Bearer; do not issue cross-port cookies.
    return {"status": "authenticated"}


@router.get("/status")
async def desktop_status(request: Request) -> dict[str, Any]:
    service = _service(request)
    state = service.settings.read()
    return {
        "configured": state.configured,
        "data_dir": str(service.settings.data_dir),
        "work_dir": state.work_dir,
        "model": {
            "provider": state.model.provider,
            "base_url": state.model.base_url,
            "model": state.model.model,
            "api_key_set": bool(state.model.api_key),
        },
        "permissions": {name: state.permissions.get(name, False) for name in EXECUTION_TOOLS},
        "busy": is_busy(request.app),
        "import_result": _import_result(service),
    }


@router.post("/setup")
async def desktop_setup(request: Request, payload: Annotated[Any, Body(...)]) -> dict[str, Any]:
    service = _service(request)
    try:
        if not isinstance(payload, dict) or set(payload) != {"model", "work_dir"}:
            raise ValueError("请提供模型设置和工作目录。")
        selected = service.settings.prepare_setup(payload["model"], payload["work_dir"])
    except ValidationError as exc:
        raise HTTPException(422, "模型设置无效，请检查提供方、地址和模型名称。") from exc
    except (TypeError, ValueError) as exc:
        raise HTTPException(422, str(exc)) from exc
    if not pause_for_restart(request.app):
        raise HTTPException(409, "还有对话或任务正在执行或排队，请结束后再保存。")
    try:
        service.settings.save(selected)
        await request.app.state.application.request_restart()
    except BaseException:
        request.app.state.execution_coordinator.resume()
        raise
    return {"status": "saved", "requires_restart": True}


class PermissionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool: Literal["bash", "code_executor"]
    authorized: bool
    acknowledgement: Literal["current-user-permissions"]


@router.post("/permissions")
async def desktop_permissions(request: Request, payload: PermissionRequest) -> dict[str, bool]:
    service = _service(request)
    state = service.settings.read()
    permissions = {**state.permissions, payload.tool: payload.authorized}
    enabled = {**state.tool_enabled, payload.tool: payload.authorized}
    service.settings.save(
        state.model_copy(update={"permissions": permissions, "tool_enabled": enabled})
    )
    registry = request.app.state.tool_registry
    registry.set_execution_permission(payload.tool, payload.authorized)
    registry.update_config(payload.tool, {"enabled": payload.authorized})
    return {"authorized": payload.authorized}
