"""Import API admission, failures and cancellation do not leave a latent import."""

from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import FastAPI, HTTPException
from starlette.requests import Request

from src.desktop.import_routes import ConfirmRequest, import_confirm
from src.desktop.import_source import ImportRejected


def request_with(importer, monkeypatch):
    app = FastAPI()
    app.state.desktop_import_lock = asyncio.Lock()
    app.state.execution_coordinator = SimpleNamespace(resume=Mock())
    app.state.application = SimpleNamespace(request_restart=AsyncMock())
    monkeypatch.setattr("src.desktop.import_routes._importer", lambda _: importer)
    monkeypatch.setattr("src.desktop.import_routes.pause_for_restart", lambda _: True)
    return Request({"type": "http", "app": app})


@pytest.mark.asyncio
async def test_successful_import_requests_restart(monkeypatch):
    importer = SimpleNamespace(stage=Mock(), abandon=Mock())
    request = request_with(importer, monkeypatch)
    result = await import_confirm(
        request, ConfirmRequest(preview_id="synthetic", acknowledgement="copy-and-pause")
    )
    assert result == {"status": "staged", "requires_restart": True}
    request.app.state.application.request_restart.assert_awaited_once()
    request.app.state.execution_coordinator.resume.assert_not_called()


@pytest.mark.asyncio
async def test_busy_import_does_not_stage(monkeypatch):
    importer = SimpleNamespace(stage=Mock(), abandon=Mock())
    request = request_with(importer, monkeypatch)
    monkeypatch.setattr("src.desktop.import_routes.pause_for_restart", lambda _: False)
    with pytest.raises(HTTPException) as error:
        await import_confirm(
            request, ConfirmRequest(preview_id="synthetic", acknowledgement="copy-and-pause")
        )
    assert error.value.status_code == 409
    importer.stage.assert_not_called()


@pytest.mark.asyncio
async def test_rejection_restores_admission(monkeypatch):
    importer = SimpleNamespace(
        stage=Mock(side_effect=ImportRejected("synthetic conflict")), abandon=Mock()
    )
    request = request_with(importer, monkeypatch)
    with pytest.raises(HTTPException) as error:
        await import_confirm(
            request, ConfirmRequest(preview_id="synthetic", acknowledgement="copy-and-pause")
        )
    assert error.value.status_code == 422
    request.app.state.execution_coordinator.resume.assert_called_once()
    request.app.state.application.request_restart.assert_not_awaited()


@pytest.mark.asyncio
async def test_cancel_waits_for_stage_then_abandons(monkeypatch):
    started = threading.Event()
    release = threading.Event()

    def stage(_):
        started.set()
        assert release.wait(timeout=5)

    importer = SimpleNamespace(stage=stage, abandon=Mock())
    request = request_with(importer, monkeypatch)
    task = asyncio.create_task(
        import_confirm(
            request, ConfirmRequest(preview_id="synthetic", acknowledgement="copy-and-pause")
        )
    )
    assert await asyncio.to_thread(started.wait, 2)
    task.cancel()
    await asyncio.sleep(0)
    request.app.state.execution_coordinator.resume.assert_not_called()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    importer.abandon.assert_called()
    request.app.state.execution_coordinator.resume.assert_called_once()
    request.app.state.application.request_restart.assert_not_awaited()
