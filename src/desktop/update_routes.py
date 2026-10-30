"""Lease-bound update admission; only the native owner selects/downloads packages."""

from __future__ import annotations

import hmac
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from src.desktop.service import pause_for_restart

router = APIRouter(prefix="/api/desktop/update", tags=["desktop"])


class UpdateLease(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lease: str = Field(min_length=32, max_length=128, pattern=r"^[a-f0-9]+$", repr=False)


@router.post("/prepare")
async def prepare_update(request: Request, payload: UpdateLease) -> dict[str, str]:
    if not pause_for_restart(request.app):
        raise HTTPException(409, "还有执行、排队或配置变更，请结束后再安装更新。")
    # No await between the shared idle check, admission close and lease publication.
    request.app.state.desktop_update_in_progress = True
    request.app.state.desktop_update_lease = payload.lease
    return {"status": "prepared", "lease": payload.lease}


@router.post("/resume")
async def resume_update(request: Request, payload: UpdateLease) -> dict[str, Literal["resumed"]]:
    current = getattr(request.app.state, "desktop_update_lease", "")
    if not current or not hmac.compare_digest(current, payload.lease):
        raise HTTPException(409, "更新状态已变化，不能恢复其它更新的接入。")
    request.app.state.desktop_update_in_progress = False
    request.app.state.desktop_update_lease = ""
    request.app.state.execution_coordinator.resume()
    return {"status": "resumed"}
