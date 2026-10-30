"""Authenticated two-step import of an explicitly selected stopped deployment."""

from __future__ import annotations

import asyncio
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from src.desktop.import_plan import OfflineImporter
from src.desktop.import_source import ImportRejected
from src.desktop.service import pause_for_restart

router = APIRouter(prefix="/api/desktop/import", tags=["desktop"])


class PreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_dir: str = Field(min_length=1, max_length=4096)
    acknowledgement: Literal["source-stopped"]


class ConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    preview_id: str = Field(min_length=1, max_length=128)
    acknowledgement: Literal["copy-and-pause"]


def _importer(request: Request) -> OfflineImporter:
    if not hasattr(request.app.state, "desktop_importer"):
        request.app.state.desktop_import_lock = asyncio.Lock()
        request.app.state.desktop_importer = OfflineImporter(
            request.app.state.desktop_service.settings
        )
    return request.app.state.desktop_importer


@router.post("/preview")
async def import_preview(request: Request, payload: PreviewRequest) -> dict:
    try:
        importer = _importer(request)
        async with request.app.state.desktop_import_lock:
            return await asyncio.to_thread(importer.preview, payload.source_dir)
    except ImportRejected as exc:
        raise HTTPException(422, str(exc)) from exc
    except (OSError, ValueError) as exc:
        raise HTTPException(422, "无法预览源数据，请检查目录与文件权限。") from exc


@router.post("/confirm")
async def import_confirm(request: Request, payload: ConfirmRequest) -> dict:
    importer = _importer(request)
    if request.app.state.desktop_import_lock.locked():
        raise HTTPException(409, "导入正在处理中，请等待。")
    if not pause_for_restart(request.app):
        raise HTTPException(409, "还有对话或任务正在执行或排队，请结束后再导入。")
    request.app.state.desktop_import_in_progress = True
    task = asyncio.create_task(asyncio.to_thread(importer.stage, payload.preview_id))
    restart_requested = False
    try:
        async with request.app.state.desktop_import_lock:
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                await task
                importer.abandon()
                raise
        await request.app.state.application.request_restart()
        restart_requested = True
    except ImportRejected as exc:
        request.app.state.execution_coordinator.resume()
        raise HTTPException(422, str(exc)) from exc
    except BaseException as exc:
        if task.done() and not task.cancelled() and task.exception() is None:
            importer.abandon()
        request.app.state.execution_coordinator.resume()
        if isinstance(exc, (OSError, ValueError)):
            raise HTTPException(422, "导入未生效，请重新预览并检查目录权限。") from exc
        raise
    finally:
        request.app.state.desktop_import_in_progress = restart_requested
    return {"status": "staged", "requires_restart": True}
