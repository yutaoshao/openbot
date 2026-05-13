from __future__ import annotations

from typing import Any

from src.tools.builtin import web_fetch
from src.tools.builtin.web_fetch import WebFetchTool


class _FakeResponse:
    text = "<html></html>"

    def raise_for_status(self) -> None:
        return None


class _FakeClient:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        return None

    async def __aenter__(self) -> _FakeClient:
        return self

    async def __aexit__(self, *args: Any) -> None:
        return None

    async def get(self, *args: Any, **kwargs: Any) -> _FakeResponse:
        return _FakeResponse()


async def test_web_fetch_returns_full_extracted_content_without_truncation(
    monkeypatch,
) -> None:
    monkeypatch.setattr(web_fetch.httpx, "AsyncClient", _FakeClient)
    monkeypatch.setattr(web_fetch.trafilatura, "extract", lambda *_, **__: "x" * 12000)
    tool = WebFetchTool()

    result = await tool.execute({"url": "https://example.com"})

    assert not result.is_error
    assert result.content == "x" * 12000
