"""Runtime settings routes."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any

from fastapi import APIRouter, Body, HTTPException, Request
from pydantic import ValidationError

from src.api.runtime_status import build_runtime_status
from src.api.schemas import (
    SettingsApplyResponse,
    SettingsSecretItem,
    SettingsSecretsResponse,
    SettingsUpdateRequest,
)
from src.core.logging import get_logger

if TYPE_CHECKING:
    from src.application.container import Application
    from src.application.settings import SettingsService
    from src.core.config import AppConfig

router = APIRouter(prefix="/api/settings", tags=["settings"])
logger = get_logger(__name__)


def _get_config(request: Request) -> AppConfig:
    config = getattr(request.app.state, "config", None)
    if config is None:
        raise HTTPException(
            status_code=503,
            detail="App config is not initialized for API requests.",
        )
    return config


def _get_settings_service(request: Request) -> SettingsService:
    service = getattr(request.app.state, "settings_service", None)
    if service is None:
        raise HTTPException(
            status_code=503,
            detail="Settings persistence is not initialized for API requests.",
        )
    return service


def _get_application(request: Request) -> Application:
    application = getattr(request.app.state, "application", None)
    if application is None:
        raise HTTPException(
            status_code=503,
            detail="Application restart control is not initialized for API requests.",
        )
    return application


def _current_restart_notice(request: Request) -> tuple[bool, list[str]]:
    return (
        bool(getattr(request.app.state, "restart_required", False)),
        list(getattr(request.app.state, "restart_reasons", [])),
    )


def _set_restart_notice(request: Request, restart_reasons: list[str]) -> None:
    if not restart_reasons:
        return
    existing = set(getattr(request.app.state, "restart_reasons", []))
    request.app.state.restart_required = True
    request.app.state.restart_reasons = [
        reason for reason in ("telegram", "model") if reason in existing | set(restart_reasons)
    ]


def _config_snapshot(request: Request, config: AppConfig) -> dict[str, Any]:
    service = getattr(request.app.state, "settings_service", None)
    snapshot = service.snapshot(config) if service else config.model_dump()
    restart_required, restart_reasons = _current_restart_notice(request)
    snapshot["runtime"] = build_runtime_status(request.app)
    snapshot["restart_required"] = restart_required
    snapshot["restart_reasons"] = restart_reasons
    return snapshot


def _settings_body(snapshot: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in snapshot.items()
        if key not in {"runtime", "restart_required", "restart_reasons"}
    }


@router.get("")
async def get_settings(request: Request) -> dict[str, Any]:
    config = _get_config(request)
    return _config_snapshot(request, config)


@router.get("/secrets", response_model=SettingsSecretsResponse)
async def get_secret_values(request: Request) -> SettingsSecretsResponse:
    config = _get_config(request)
    service = _get_settings_service(request)
    secrets = [
        SettingsSecretItem(
            env_name=item.env_name,
            value=item.value,
            is_set=item.is_set,
        )
        for item in service.read_secret_values(config)
    ]
    return SettingsSecretsResponse(secrets=secrets)


@router.put("")
async def update_settings(
    request: Request,
    payload: Annotated[Any, Body(...)],
) -> dict[str, Any]:
    config = _get_config(request)
    service = _get_settings_service(request)

    try:
        patch = SettingsUpdateRequest.model_validate(payload).model_dump(exclude_none=True)
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid settings payload: {exc}") from exc

    try:
        result = service.update_config(config, patch)
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid settings payload: {exc}") from exc
    except OSError as exc:
        logger.exception("settings.persist_failed")
        raise HTTPException(status_code=500, detail="Failed to persist settings.") from exc

    request.app.state.config = result.config
    _set_restart_notice(request, result.restart_reasons)
    snapshot = _config_snapshot(request, result.config)
    return {
        "status": "updated",
        "settings": _settings_body(snapshot),
        "runtime": snapshot["runtime"],
        "restart_required": snapshot["restart_required"],
        "restart_reasons": snapshot["restart_reasons"],
    }


@router.post("/apply", response_model=SettingsApplyResponse)
async def apply_saved_settings(request: Request) -> SettingsApplyResponse:
    application = _get_application(request)
    restart_required, restart_reasons = _current_restart_notice(request)
    await application.request_restart()
    return SettingsApplyResponse(
        status="restarting",
        restart_required=restart_required,
        restart_reasons=restart_reasons,
    )
