"""Feishu API client for token management and outbound requests."""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Any

import httpx

from src.core.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import Mapping

    from src.core.config import FeishuConfig

logger = get_logger(__name__)

FEISHU_API_BASE = "https://open.feishu.cn/open-apis"
FEISHU_MESSAGES_PATH = "/im/v1/messages"
_FEISHU_TOKEN_PATH = "/auth/v3/tenant_access_token/internal"
_TOKEN_REFRESH_BUFFER_SECONDS = 300
_HTTP_TIMEOUT_SECONDS = 30.0
_REQUEST_RETRY_ATTEMPTS = 2
_RETRY_BASE_DELAY_SECONDS = 1.0
_RETRYABLE_HTTP_STATUSES = {408, 429, 500, 502, 503, 504}


class FeishuApiClient:
    """Thin client for Feishu tenant-token and message APIs."""

    def __init__(self, config: FeishuConfig) -> None:
        self._config = config
        self._tenant_token = ""
        self._token_expires_at = 0.0
        self._client: httpx.AsyncClient | None = None

    @property
    def client(self) -> httpx.AsyncClient | None:
        return self._client

    @client.setter
    def client(self, value: httpx.AsyncClient | None) -> None:
        self._client = value

    @property
    def tenant_token(self) -> str:
        return self._tenant_token

    async def start(self) -> None:
        self._client = httpx.AsyncClient(timeout=_HTTP_TIMEOUT_SECONDS)
        await self.refresh_token(force=True)

    async def stop(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def refresh_token(self, *, force: bool = False) -> str:
        """Fetch or refresh the tenant access token."""
        if self._client is None:
            raise RuntimeError("Feishu client not initialized.")
        if not force and self._tenant_token and time.monotonic() < self._token_expires_at:
            return self._tenant_token
        for attempt in range(1, _REQUEST_RETRY_ATTEMPTS + 1):
            try:
                response = await self._client.post(
                    f"{FEISHU_API_BASE}{_FEISHU_TOKEN_PATH}",
                    json={
                        "app_id": self._config.app_id,
                        "app_secret": self._config.app_secret,
                    },
                )
                result = self._parse_response(response, _FEISHU_TOKEN_PATH)
                if result.get("code") != 0:
                    raise RuntimeError(self.format_api_error(_FEISHU_TOKEN_PATH, result))
                expire = int(result.get("expire", 7200))
                self._tenant_token = str(result.get("tenant_access_token", ""))
                self._token_expires_at = (
                    time.monotonic() + expire - _TOKEN_REFRESH_BUFFER_SECONDS
                )
                logger.info(
                    "feishu.token_refreshed",
                    expires_in=expire,
                    request_id=result.get("_request_id"),
                )
                return self._tenant_token
            except Exception as exc:
                if attempt == _REQUEST_RETRY_ATTEMPTS:
                    logger.exception("feishu.token_refresh_failed")
                    raise RuntimeError("Failed to refresh Feishu tenant token.") from exc
                await self._sleep_before_retry(
                    "feishu.token_refresh_retry",
                    attempt=attempt,
                    error=type(exc).__name__,
                )
        raise RuntimeError("Failed to refresh Feishu tenant token.")

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Make an authenticated Feishu API request with retries."""
        if self._client is None:
            return self.error_result("request_error", "Feishu client not initialized.")
        token_retry_used = False
        for attempt in range(1, _REQUEST_RETRY_ATTEMPTS + 1):
            token = await self._ensure_token(force_refresh=False)
            result = await self._request_once(method, path, token, params=params, json=json)
            if result.get("code") == 0:
                result["_retried"] = token_retry_used or attempt > 1
                return result
            if result.get("_http_status") == 401 and not token_retry_used:
                logger.warning("feishu.api_token_retry", path=path, http_status=401)
                await self.refresh_token(force=True)
                token_retry_used = True
                continue
            if attempt == _REQUEST_RETRY_ATTEMPTS or not self._is_retryable(result):
                result["_retried"] = token_retry_used or attempt > 1
                return result
            await self._sleep_before_retry(
                "feishu.api_retry",
                attempt=attempt,
                path=path,
                http_status=result.get("_http_status"),
                error_type=result.get("_error_type"),
                feishu_code=result.get("code"),
            )
        return self.error_result("request_error", "Feishu request retry loop exhausted.")

    async def _ensure_token(self, *, force_refresh: bool = False) -> str:
        if force_refresh or not self._tenant_token or time.monotonic() >= self._token_expires_at:
            return await self.refresh_token(force=True)
        return self._tenant_token

    async def _request_once(
        self,
        method: str,
        path: str,
        token: str,
        *,
        params: dict[str, str] | None = None,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        assert self._client is not None
        try:
            response = await self._client.request(
                method,
                f"{FEISHU_API_BASE}{path}",
                headers={"Authorization": f"Bearer {token}"},
                params=params,
                json=json,
            )
        except httpx.RequestError as exc:
            logger.warning(
                "feishu.api_request_failed",
                path=path,
                error_type=type(exc).__name__,
                error=str(exc),
            )
            return self.error_result("request_error", str(exc))
        return self._parse_response(response, path)

    def _parse_response(self, response: httpx.Response, path: str) -> dict[str, Any]:
        request_id = response.headers.get("x-tt-logid", response.headers.get("x-request-id", ""))
        if response.status_code >= 400:
            logger.error(
                "feishu.api_http_error",
                path=path,
                http_status=response.status_code,
                request_id=request_id,
            )
            return self.error_result(
                "http_error",
                response.text or response.reason_phrase,
                http_status=response.status_code,
                request_id=request_id,
                code=response.status_code,
            )
        try:
            data = response.json()
        except ValueError:
            logger.error(
                "feishu.api_invalid_json",
                path=path,
                http_status=response.status_code,
                request_id=request_id,
            )
            return self.error_result(
                "http_error",
                "Invalid JSON response from Feishu API.",
                http_status=response.status_code,
                request_id=request_id,
            )
        if not isinstance(data, dict):
            return self.error_result(
                "api_error",
                "Feishu API response must be a JSON object.",
                http_status=response.status_code,
                request_id=request_id,
            )
        if data.get("code") != 0:
            logger.warning(
                "feishu.api_error",
                path=path,
                http_status=response.status_code,
                request_id=request_id,
                feishu_code=data.get("code"),
                feishu_msg=data.get("msg"),
            )
        data["_error_type"] = "api_error" if data.get("code") != 0 else "none"
        data["_http_status"] = response.status_code
        data["_request_id"] = request_id
        return data

    @staticmethod
    def error_result(
        error_type: str,
        message: str,
        *,
        http_status: int | None = None,
        request_id: str = "",
        code: int = -1,
    ) -> dict[str, Any]:
        return {
            "code": code,
            "msg": message,
            "_error_type": error_type,
            "_http_status": http_status,
            "_request_id": request_id,
        }

    @staticmethod
    def format_api_error(path: str, result: Mapping[str, Any]) -> str:
        return (
            f"Feishu API request failed for {path}: "
            f"error_type={result.get('_error_type')} "
            f"http_status={result.get('_http_status')} "
            f"code={result.get('code')} "
            f"request_id={result.get('_request_id', '')} "
            f"msg={result.get('msg', '')}"
        )

    @staticmethod
    def _is_retryable(result: Mapping[str, Any]) -> bool:
        if result.get("_error_type") == "request_error":
            return True
        return result.get("_http_status") in _RETRYABLE_HTTP_STATUSES

    @staticmethod
    async def _sleep_before_retry(event: str, **fields: Any) -> None:
        delay = _RETRY_BASE_DELAY_SECONDS * fields["attempt"]
        logger.warning(event, delay_seconds=delay, **fields)
        await asyncio.sleep(delay)
