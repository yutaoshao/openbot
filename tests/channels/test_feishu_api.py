from __future__ import annotations

import time
from typing import Any

import httpx

from src.channels.adapters.feishu_api import FeishuApiClient
from src.core.config import FeishuConfig


def _set_feishu_env(monkeypatch: Any) -> None:
    monkeypatch.setenv("FEISHU_APP_ID", "cli_test")
    monkeypatch.setenv("FEISHU_APP_SECRET", "secret_test")
    monkeypatch.setenv("FEISHU_VERIFICATION_TOKEN", "verify_test")
    monkeypatch.setenv("FEISHU_ENCRYPT_KEY", "encrypt_test")


def _response(
    method: str,
    url: str,
    status_code: int,
    *,
    json_body: dict[str, Any] | None = None,
    text: str = "",
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    request = httpx.Request(method, url)
    if json_body is not None:
        return httpx.Response(
            status_code,
            request=request,
            json=json_body,
            headers=headers,
        )
    return httpx.Response(
        status_code,
        request=request,
        text=text,
        headers=headers,
    )


class _FakeAsyncClient:
    def __init__(
        self,
        *,
        post_results: list[httpx.Response | Exception] | None = None,
        request_results: list[httpx.Response | Exception] | None = None,
    ) -> None:
        self._post_results = list(post_results or [])
        self._request_results = list(request_results or [])
        self.closed = False

    async def post(self, *args: Any, **kwargs: Any) -> httpx.Response:
        return self._pop(self._post_results)

    async def request(self, *args: Any, **kwargs: Any) -> httpx.Response:
        return self._pop(self._request_results)

    async def aclose(self) -> None:
        self.closed = True

    @staticmethod
    def _pop(queue: list[httpx.Response | Exception]) -> httpx.Response:
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


async def test_refresh_token_stores_token_and_expiry(monkeypatch: Any) -> None:
    _set_feishu_env(monkeypatch)
    api_client = FeishuApiClient(FeishuConfig(enabled=True))
    api_client.client = _FakeAsyncClient(
        post_results=[
            _response(
                "POST",
                "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
                200,
                json_body={"code": 0, "tenant_access_token": "tenant_token", "expire": 7200},
            ),
        ]
    )

    before = time.monotonic()
    token = await api_client.refresh_token(force=True)

    assert token == "tenant_token"
    assert api_client.tenant_token == "tenant_token"
    assert api_client._token_expires_at > before


async def test_refresh_token_raises_on_business_error(monkeypatch: Any) -> None:
    _set_feishu_env(monkeypatch)
    api_client = FeishuApiClient(FeishuConfig(enabled=True))
    api_client.client = _FakeAsyncClient(
        post_results=[
            _response(
                "POST",
                "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
                200,
                json_body={"code": 999, "msg": "bad credentials"},
            ),
        ]
    )

    try:
        await api_client.refresh_token(force=True)
    except RuntimeError as exc:
        assert "Failed to refresh Feishu tenant token." in str(exc)
    else:
        raise AssertionError("expected token refresh failure")


async def test_refresh_token_raises_on_http_error(monkeypatch: Any) -> None:
    _set_feishu_env(monkeypatch)
    api_client = FeishuApiClient(FeishuConfig(enabled=True))
    api_client.client = _FakeAsyncClient(
        post_results=[
            _response(
                "POST",
                "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
                503,
                text="service unavailable",
            ),
            _response(
                "POST",
                "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
                503,
                text="service unavailable",
            ),
        ]
    )

    try:
        await api_client.refresh_token(force=True)
    except RuntimeError as exc:
        assert "Failed to refresh Feishu tenant token." in str(exc)
    else:
        raise AssertionError("expected token refresh failure")


async def test_request_refreshes_token_after_401(monkeypatch: Any) -> None:
    _set_feishu_env(monkeypatch)
    api_client = FeishuApiClient(FeishuConfig(enabled=True))
    api_client.client = _FakeAsyncClient(
        post_results=[
            _response(
                "POST",
                "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
                200,
                json_body={"code": 0, "tenant_access_token": "fresh_token", "expire": 7200},
            ),
        ],
        request_results=[
            _response(
                "POST",
                "https://open.feishu.cn/open-apis/im/v1/messages",
                401,
                text="unauthorized",
            ),
            _response(
                "POST",
                "https://open.feishu.cn/open-apis/im/v1/messages",
                200,
                json_body={"code": 0, "msg": "ok"},
            ),
        ],
    )
    api_client._tenant_token = "stale_token"
    api_client._token_expires_at = time.monotonic() + 60

    result = await api_client.request("POST", "/im/v1/messages", json={"msg_type": "text"})

    assert result["code"] == 0
    assert result["_retried"] is True
    assert api_client.tenant_token == "fresh_token"
