"""Runtime settings routes."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from src.api.runtime_status import build_runtime_status
from src.core.config import AppConfig

router = APIRouter(prefix="/api/settings", tags=["settings"])


def _deep_update(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(base)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_update(result[key], value)
        else:
            result[key] = value
    return result


def _get_config(request: Request) -> AppConfig:
    config = getattr(request.app.state, "config", None)
    if config is None:
        raise HTTPException(
            status_code=503,
            detail="App config is not initialized for API requests.",
        )
    return config


@router.get("")
async def get_settings(request: Request) -> dict[str, Any]:
    config = _get_config(request)
    settings = config.model_dump()
    settings["runtime"] = build_runtime_status(request.app)
    return settings


@router.put("")
async def update_settings(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
    config = _get_config(request)
    current = config.model_dump()
    merged = _deep_update(current, payload)

    try:
        updated = AppConfig(**merged)
    except Exception as e:  # pydantic validation error types vary
        raise HTTPException(status_code=400, detail=f"Invalid settings payload: {e}") from e

    request.app.state.config = updated
    return {
        "status": "updated",
        "settings": updated.model_dump(),
    }
