"""Exclude new management writes while the owned data or application is replaced."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import FastAPI


def maintenance_in_progress(api: FastAPI) -> bool:
    application = getattr(api.state, "application", None)
    return (
        getattr(api.state, "desktop_import_in_progress", False) is True
        or getattr(api.state, "desktop_update_in_progress", False) is True
        or getattr(application, "restart_requested", False) is True
    )


def login_in_progress(api: FastAPI) -> bool:
    service = getattr(api.state, "desktop_service", None)
    login = getattr(service, "wechat_login", None)
    return login is not None and login.active


def other_management_writes(api: FastAPI) -> bool:
    # The transition endpoint is itself one authenticated write. Counting at the
    # ASGI boundary also includes mutations that do not run an Agent turn.
    return getattr(api.state, "desktop_mutations", 0) > 1
