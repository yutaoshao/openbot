"""One finite login operation, with credentials kept out of browser responses."""

from __future__ import annotations

import asyncio
import base64
import io
import secrets
import time
from dataclasses import asdict
from urllib.parse import urlsplit

import qrcode

from src.channels.adapters.wechat_ilink_api import WeChatIlinkClient
from src.channels.adapters.wechat_state import WeChatLoginState, WeChatStateStore
from src.desktop.settings import DesktopSettings, write_private_json

LOGIN_SECONDS = 480


def _allowed_endpoint(value: str) -> str:
    host = urlsplit(value).hostname or ""
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not (host == "weixin.qq.com" or host.endswith(".weixin.qq.com"))
        or parsed.username
        or parsed.password
        or parsed.port not in (None, 443)
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Invalid WeChat login endpoint")
    return value.rstrip("/")


class DesktopWeChatLogin:
    def __init__(self, settings: DesktopSettings) -> None:
        self.settings = settings
        self._task: asyncio.Task | None = None
        self._session: dict | None = None
        self._deadline = 0.0
        self._lock = asyncio.Lock()

    @property
    def active(self) -> bool:
        return self._lock.locked() or bool(self._task and not self._task.done())

    def snapshot(self, session_id: str) -> dict | None:
        if not self._session or self._session["session_id"] != session_id:
            return None
        return {**self._session, "expires_in": max(0, int(self._deadline - time.monotonic()))}

    async def cancel(self, session_id: str | None = None) -> bool:
        async with self._lock:
            if session_id is not None and self.snapshot(session_id) is None:
                return False
            await self._cancel_current()
            return True

    async def _cancel_current(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
        if self._session and self._session["status"] not in {"confirmed", "expired", "failed"}:
            self._session = {**self._session, "status": "cancelled", "qr_image": ""}

    async def start(self, endpoint: str) -> dict:
        async with self._lock:
            await self._cancel_current()
            client = WeChatIlinkClient(_allowed_endpoint(endpoint))
            await client.start()
            try:
                payload = await client.fetch_login_qrcode()
                output = io.BytesIO()
                qrcode.make(payload["qrcode_img_content"]).save(output, format="PNG")
                self._deadline = time.monotonic() + LOGIN_SECONDS
                self._session = {
                    "session_id": secrets.token_urlsafe(24),
                    "status": "wait",
                    "qr_image": "data:image/png;base64,"
                    + base64.b64encode(output.getvalue()).decode(),
                }
                self._task = asyncio.create_task(self._poll(client, payload["qrcode"], endpoint))
                return self.snapshot(self._session["session_id"])
            except BaseException:
                await client.stop()
                raise

    async def _poll(self, client: WeChatIlinkClient, code: str, endpoint: str) -> None:
        try:
            async with asyncio.timeout(LOGIN_SECONDS):
                while True:
                    result = await client.poll_login_status(qrcode=code, base_url=endpoint)
                    status = result.get("status", "wait")
                    if status == "confirmed":
                        state = WeChatLoginState(
                            account_id=result.get("ilink_bot_id", "").strip(),
                            bot_token=result.get("bot_token", "").strip(),
                            api_base_url=endpoint,
                            user_id=result.get("ilink_user_id", ""),
                        )
                        if not state.is_valid:
                            raise ValueError("Incomplete login response")
                        path = WeChatStateStore(
                            str(self.settings.data_dir / "data/wechat/ilink_state.json")
                        ).path
                        write_private_json(path, asdict(state))
                        self._session = {**self._session, "status": "confirmed", "qr_image": ""}
                        return
                    if status == "expired":
                        self._session = {**self._session, "status": "expired", "qr_image": ""}
                        return
                    if status == "scaned_but_redirect":
                        endpoint = _allowed_endpoint(result.get("redirect_host", ""))
                    elif status in {"wait", "scaned"}:
                        self._session = {
                            **self._session,
                            "status": "scanned" if status == "scaned" else "wait",
                        }
                    else:
                        raise ValueError("Unknown login response")
                    await asyncio.sleep(1)
        except TimeoutError:
            self._session = {**self._session, "status": "expired", "qr_image": ""}
        except asyncio.CancelledError:
            raise
        except Exception:
            self._session = {**self._session, "status": "failed", "qr_image": ""}
        finally:
            await client.stop()
