"""Helpers for runtime adapter status exposed via the API."""

from __future__ import annotations

from typing import Any


def build_runtime_status(app: Any) -> dict[str, dict[str, str | bool | list[str] | None]]:
    """Build a lightweight runtime status snapshot for adapters and API."""
    config = getattr(app.state, "config", None)
    feishu_config = getattr(config, "feishu", None)
    telegram_config = getattr(config, "telegram", None)
    api_config = getattr(config, "api", None)

    feishu_missing = feishu_config.missing_required_env_vars() if feishu_config else []
    telegram_missing = (
        telegram_config.missing_required_env_vars()
        if telegram_config and hasattr(telegram_config, "missing_required_env_vars")
        else []
    )
    feishu_adapter = getattr(app.state, "feishu", None)
    telegram_adapter = getattr(app.state, "telegram", None)

    return {
        "api": {
            "enabled": bool(getattr(api_config, "enabled", False)),
            "host": getattr(api_config, "host", None),
            "port": str(getattr(api_config, "port", "")) or None,
            "status": "ready",
        },
        "telegram": {
            "enabled": bool(getattr(telegram_config, "enabled", False)),
            "mode": getattr(telegram_config, "mode", None),
            "status": _telegram_status(telegram_config, telegram_adapter, telegram_missing),
            "missing_env_vars": telegram_missing,
        },
        "feishu": {
            "enabled": bool(getattr(feishu_config, "enabled", False)),
            "mode": getattr(feishu_config, "mode", None),
            "status": _feishu_status(feishu_config, feishu_adapter, feishu_missing),
            "missing_env_vars": feishu_missing,
        },
    }


def _feishu_status(feishu_config: Any, adapter: Any, missing_envs: list[str]) -> str:
    """Resolve the user-facing Feishu runtime status."""
    if not getattr(feishu_config, "enabled", False):
        return "disabled"
    if missing_envs:
        return "incomplete"
    if adapter is None:
        return "starting"
    return "ready"


def _telegram_status(telegram_config: Any, adapter: Any, missing_envs: list[str]) -> str:
    """Resolve the user-facing Telegram runtime status."""
    if not getattr(telegram_config, "enabled", False):
        return "disabled"
    if missing_envs:
        return "incomplete"
    if adapter is None:
        return "starting"
    return "ready"
