"""Local-only access guards for management HTTP and WebSocket surfaces."""

from __future__ import annotations

from ipaddress import ip_address
from typing import TYPE_CHECKING, Any

from fastapi.responses import JSONResponse

if TYPE_CHECKING:
    from fastapi import Request, WebSocket

LOCAL_ACCESS_DENIED_DETAIL = "OpenBot management surfaces are restricted to local access."
_REMOTE_ALLOWED_PREFIXES = ("/webhook",)
_SPECIAL_LOCAL_HOSTS = {"localhost", "testclient"}


def is_local_only_enabled(app: Any) -> bool:
    """Return ``True`` when local-only access restrictions are enabled."""
    config = getattr(app.state, "runtime_config", None) or getattr(app.state, "config", None)
    api_config = getattr(config, "api", None)
    return bool(getattr(api_config, "local_only", False))


def allows_remote_path(path: str) -> bool:
    """Return ``True`` when *path* is intentionally reachable remotely."""
    return any(
        path == prefix or path.startswith(f"{prefix}/") for prefix in _REMOTE_ALLOWED_PREFIXES
    )


def is_loopback_host(host: str | None) -> bool:
    """Return ``True`` for loopback IPs and test-only local client labels."""
    if not host:
        return False
    if host in _SPECIAL_LOCAL_HOSTS:
        return True
    try:
        return ip_address(host).is_loopback
    except ValueError:
        return False


async def enforce_local_request(request: Request, call_next: Any):
    """Reject remote HTTP requests when the app is in local-only mode."""
    if not is_local_only_enabled(request.app) or allows_remote_path(request.url.path):
        return await call_next(request)
    client_host = request.client.host if request.client else None
    if is_loopback_host(client_host):
        return await call_next(request)
    return JSONResponse(status_code=403, content={"detail": LOCAL_ACCESS_DENIED_DETAIL})


def websocket_requires_local_access(websocket: WebSocket) -> bool:
    """Return ``True`` when a WebSocket client should be denied."""
    if not is_local_only_enabled(websocket.app) or allows_remote_path(websocket.url.path):
        return False
    client_host = websocket.client.host if websocket.client else None
    return not is_loopback_host(client_host)
