"""Minimal iLink API client for the WeChat personal account adapter."""

from __future__ import annotations

import base64
import json
import secrets
from importlib.metadata import PackageNotFoundError, version
from typing import Any, TypedDict
from urllib.parse import quote

import httpx

from src.core.logging import get_logger

logger = get_logger(__name__)

DEFAULT_WECHAT_API_BASE = "https://ilinkai.weixin.qq.com"
DEFAULT_ILINK_BOT_TYPE = "3"
_ILINK_APP_ID = "bot"
_DEFAULT_API_TIMEOUT_SECONDS = 15.0
_DEFAULT_LONG_POLL_TIMEOUT_MS = 35_000


class QRCodeLoginPayload(TypedDict):
    qrcode: str
    qrcode_img_content: str


class QRCodeStatusPayload(TypedDict, total=False):
    status: str
    bot_token: str
    ilink_bot_id: str
    ilink_user_id: str
    redirect_host: str


class ILinkApiError(RuntimeError):
    """Structured error for iLink API failures."""

    def __init__(
        self,
        message: str,
        *,
        errcode: int | None = None,
        errmsg: str | None = None,
    ) -> None:
        super().__init__(message)
        self.errcode = errcode
        self.errmsg = errmsg


def _channel_version() -> str:
    try:
        return version("openbot")
    except PackageNotFoundError:
        return "0.1.0"


def _client_version(version_text: str) -> int:
    parts = [int(part) if part.isdigit() else 0 for part in version_text.split(".")]
    major, minor, patch = (parts + [0, 0, 0])[:3]
    return ((major & 0xFF) << 16) | ((minor & 0xFF) << 8) | (patch & 0xFF)


class WeChatIlinkClient:
    """Async wrapper for the subset of iLink endpoints used by OpenBot."""

    def __init__(self, base_url: str = DEFAULT_WECHAT_API_BASE) -> None:
        self._default_base_url = base_url.rstrip("/")
        self._channel_version = _channel_version()
        self._client_version = _client_version(self._channel_version)
        self._client: httpx.AsyncClient | None = None

    async def start(self) -> None:
        self._client = httpx.AsyncClient(timeout=_DEFAULT_API_TIMEOUT_SECONDS)

    async def stop(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def fetch_login_qrcode(
        self,
        *,
        bot_type: str = DEFAULT_ILINK_BOT_TYPE,
        base_url: str | None = None,
    ) -> QRCodeLoginPayload:
        endpoint = f"ilink/bot/get_bot_qrcode?bot_type={quote(bot_type)}"
        payload = await self._get_json(endpoint, base_url=base_url)
        return {
            "qrcode": str(payload["qrcode"]),
            "qrcode_img_content": str(payload["qrcode_img_content"]),
        }

    async def poll_login_status(
        self,
        *,
        qrcode: str,
        base_url: str | None = None,
    ) -> QRCodeStatusPayload:
        endpoint = f"ilink/bot/get_qrcode_status?qrcode={quote(qrcode)}"
        try:
            payload = await self._get_json(
                endpoint,
                base_url=base_url,
                timeout=httpx.Timeout(connect=10.0, read=40.0, write=10.0, pool=10.0),
            )
        except httpx.ReadTimeout:
            return {"status": "wait"}
        status = str(payload.get("status", "wait"))
        result: QRCodeStatusPayload = {"status": status}
        for key in ("bot_token", "ilink_bot_id", "ilink_user_id", "redirect_host"):
            value = payload.get(key)
            if isinstance(value, str) and value:
                result[key] = value
        return result

    async def get_updates(
        self,
        *,
        bot_token: str,
        get_updates_buf: str = "",
        base_url: str | None = None,
        timeout_ms: int = _DEFAULT_LONG_POLL_TIMEOUT_MS,
    ) -> dict[str, Any]:
        try:
            payload = await self._post_json(
                "ilink/bot/getupdates",
                {
                    "get_updates_buf": get_updates_buf,
                    "base_info": {"channel_version": self._channel_version},
                },
                token=bot_token,
                base_url=base_url,
                timeout=httpx.Timeout(
                    connect=10.0,
                    read=max((timeout_ms / 1000) + 5.0, 40.0),
                    write=10.0,
                    pool=10.0,
                ),
            )
        except httpx.ReadTimeout:
            return {"ret": 0, "msgs": [], "get_updates_buf": get_updates_buf}
        self._raise_if_api_error("getupdates", payload)
        return payload

    async def send_text_message(
        self,
        *,
        bot_token: str,
        to_user_id: str,
        text: str,
        context_token: str,
        base_url: str | None = None,
    ) -> dict[str, Any]:
        payload = await self._post_json(
            "ilink/bot/sendmessage",
            {
                "msg": {
                    "from_user_id": "",
                    "to_user_id": to_user_id,
                    "client_id": secrets.token_hex(8),
                    "message_type": 2,
                    "message_state": 2,
                    "context_token": context_token,
                    "item_list": [
                        {
                            "type": 1,
                            "text_item": {"text": text},
                        }
                    ],
                },
                "base_info": {"channel_version": self._channel_version},
            },
            token=bot_token,
            base_url=base_url,
        )
        self._raise_if_api_error("sendmessage", payload)
        return payload

    async def _get_json(
        self,
        endpoint: str,
        *,
        base_url: str | None = None,
        timeout: httpx.Timeout | float | None = None,
    ) -> dict[str, Any]:
        client = self._require_client()
        response = await client.get(
            self._url(endpoint, base_url),
            headers=self._common_headers(),
            timeout=timeout,
        )
        response.raise_for_status()
        return self._parse_json(response, endpoint)

    async def _post_json(
        self,
        endpoint: str,
        body: dict[str, Any],
        *,
        token: str,
        base_url: str | None = None,
        timeout: httpx.Timeout | float | None = None,
    ) -> dict[str, Any]:
        client = self._require_client()
        response = await client.post(
            self._url(endpoint, base_url),
            content=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers=self._request_headers(token),
            timeout=timeout,
        )
        response.raise_for_status()
        return self._parse_json(response, endpoint)

    def _parse_json(self, response: httpx.Response, endpoint: str) -> dict[str, Any]:
        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError(f"Unexpected iLink response for {endpoint}: {payload!r}")
        return payload

    def _request_headers(self, token: str) -> dict[str, str]:
        headers = self._common_headers()
        headers.update(
            {
                "Content-Type": "application/json",
                "AuthorizationType": "ilink_bot_token",
                "Authorization": f"Bearer {token}",
                "X-WECHAT-UIN": self._wechat_uin(),
            }
        )
        return headers

    def _common_headers(self) -> dict[str, str]:
        return {
            "iLink-App-Id": _ILINK_APP_ID,
            "iLink-App-ClientVersion": str(self._client_version),
        }

    def _url(self, endpoint: str, base_url: str | None) -> str:
        root = (base_url or self._default_base_url).rstrip("/")
        return f"{root}/{endpoint.lstrip('/')}"

    def _require_client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("WeChat iLink client is not started.")
        return self._client

    def _raise_if_api_error(self, endpoint: str, payload: dict[str, Any]) -> None:
        ret = payload.get("ret")
        errcode = payload.get("errcode")
        if ret in (None, 0) and errcode in (None, 0):
            return
        raise ILinkApiError(
            "iLink "
            f"{endpoint} failed: ret={ret} errcode={errcode} "
            f"errmsg={payload.get('errmsg', '')}",
            errcode=errcode if isinstance(errcode, int) else None,
            errmsg=str(payload.get("errmsg", "")),
        )

    @staticmethod
    def _wechat_uin() -> str:
        value = str(secrets.randbits(32))
        return base64.b64encode(value.encode("utf-8")).decode("utf-8")
