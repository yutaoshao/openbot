"""Authentication for the loopback service owned by one native app instance."""

from __future__ import annotations

import hmac
from typing import TYPE_CHECKING

from starlette.responses import JSONResponse

from src.desktop.maintenance import maintenance_in_progress

if TYPE_CHECKING:
    from collections.abc import Callable

    from starlette.types import ASGIApp, Receive, Scope, Send


class DesktopAuthentication:
    """Keep native credentials out of URLs, static resources and persisted state."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        token: str,
        origins: list[str],
        is_configured: Callable[[], bool],
    ) -> None:
        self.app = app
        self._expected = f"Bearer {token}".encode()
        self._websocket_protocol = f"openbot.auth.{token}".encode()
        self._origins = frozenset(origins)
        self._is_configured = is_configured

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        kind, path = scope["type"], scope.get("path", "")
        if kind not in {"http", "websocket"} or not _is_management_path(path):
            await self.app(scope, receive, send)
            return
        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        origin = headers.get(b"origin", b"").decode("latin-1")
        origin_allowed = not origin or origin in self._origins
        preflight = kind == "http" and scope.get("method") == "OPTIONS"
        authorized = hmac.compare_digest(headers.get(b"authorization", b""), self._expected)
        if kind == "websocket":
            authorized = authorized or any(
                hmac.compare_digest(value.strip(), self._websocket_protocol)
                for value in headers.get(b"sec-websocket-protocol", b"").split(b",")
            )
        if not origin_allowed or (not preflight and not authorized):
            code = 403 if not origin_allowed else 401
            await _deny(kind, scope, receive, send, code, "Desktop authentication required.")
            return
        if not preflight and _is_chat_path(path) and not self._is_configured():
            await _deny(kind, scope, receive, send, 409, "请先完成模型配置。")
            return
        api = scope["app"]
        mutating = kind == "http" and scope.get("method") not in {"GET", "HEAD", "OPTIONS"}
        if maintenance_in_progress(api) and (
            (mutating and path != "/api/desktop/update/resume")
            or (kind == "websocket" and _is_chat_path(path))
        ):
            await _deny(kind, scope, receive, send, 409, "应用正在导入、更新或重启，请稍后再操作。")
            return
        if mutating:
            api.state.desktop_mutations = getattr(api.state, "desktop_mutations", 0) + 1
        try:
            await self.app(scope, receive, send)
        finally:
            if mutating:
                api.state.desktop_mutations -= 1


def _is_management_path(path: str) -> bool:
    return path == "/health" or path == "/api" or path.startswith(("/api/", "/ws/"))


def _is_chat_path(path: str) -> bool:
    return path in {"/api/chat", "/api/ws/chat"} or path.startswith("/api/chat/")


async def _deny(kind: str, scope: Scope, receive: Receive, send: Send, status: int, detail: str):
    if kind == "websocket":
        await send({"type": "websocket.close", "code": 1008})
        return
    headers = {"X-OpenBot-Desktop": "1"}
    if status == 401:
        headers["WWW-Authenticate"] = "Bearer"
    await JSONResponse({"detail": detail}, status_code=status, headers=headers)(
        scope, receive, send
    )
