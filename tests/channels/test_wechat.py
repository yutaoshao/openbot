"""Tests for the WeChat iLink adapter."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from src.channels.adapters.wechat import (
    _PROACTIVE_SEND_UNSUPPORTED,
    _TEXT_ONLY_REPLY,
    WeChatAdapter,
)
from src.channels.adapters.wechat_state import WeChatLoginState
from src.channels.types import MessageContent
from src.core.config import WeChatConfig


class _FakeMsgHub:
    def __init__(self) -> None:
        self.messages: list[Any] = []

    async def handle_incoming(self, message: Any) -> None:
        self.messages.append(message)


class _FakeStateStore:
    def __init__(self, state: WeChatLoginState | None) -> None:
        self._state = state

    def load(self) -> WeChatLoginState | None:
        return self._state

    def update_get_updates_buf(self, get_updates_buf: str) -> WeChatLoginState | None:
        if self._state is not None:
            self._state.get_updates_buf = get_updates_buf
        return self._state

    def update_api_base_url(self, api_base_url: str) -> WeChatLoginState | None:
        if self._state is not None:
            self._state.api_base_url = api_base_url
        return self._state


class _FakeIlinkClient:
    def __init__(self) -> None:
        self.sent_messages: list[dict[str, str]] = []
        self.get_updates_calls = 0
        self.fail_first_poll = False
        self._adapter: WeChatAdapter | None = None

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    async def get_updates(
        self,
        *,
        bot_token: str,
        get_updates_buf: str = "",
        base_url: str | None = None,
        timeout_ms: int = 35_000,
    ) -> dict[str, Any]:
        self.get_updates_calls += 1
        if self.fail_first_poll and self.get_updates_calls == 1:
            raise RuntimeError("temporary iLink failure")
        if self._adapter is not None and self.get_updates_calls >= 2:
            self._adapter._stop_event.set()  # noqa: SLF001
        return {"ret": 0, "msgs": [], "get_updates_buf": get_updates_buf}

    async def send_text_message(
        self,
        *,
        bot_token: str,
        to_user_id: str,
        text: str,
        context_token: str,
        base_url: str | None = None,
    ) -> dict[str, Any]:
        self.sent_messages.append({
            "bot_token": bot_token,
            "to_user_id": to_user_id,
            "text": text,
            "context_token": context_token,
            "base_url": base_url or "",
        })
        return {}


def _state() -> WeChatLoginState:
    return WeChatLoginState(
        account_id="acc-1",
        bot_token="bot-token",
        api_base_url="https://ilinkai.weixin.qq.com",
    )


async def test_handle_inbound_text_message_routes_to_msg_hub() -> None:
    hub = _FakeMsgHub()
    adapter = WeChatAdapter(
        WeChatConfig(enabled=True),
        hub,  # type: ignore[arg-type]
        state_store=_FakeStateStore(_state()),
        api_client=_FakeIlinkClient(),
    )
    adapter._state = _state()  # noqa: SLF001

    await adapter._handle_inbound_message({  # noqa: SLF001
        "message_id": 101,
        "from_user_id": "wx-user-1",
        "message_type": 1,
        "context_token": "ctx-1",
        "item_list": [{"type": 1, "text_item": {"text": "你好"}}],
    })

    assert len(hub.messages) == 1
    message = hub.messages[0]
    assert message.platform == "wechat"
    assert message.sender_id == "wx-user-1"
    assert message.conversation_id == "wechat:acc-1:wx-user-1"
    assert message.content.text == "你好"


async def test_handle_inbound_group_message_is_ignored() -> None:
    hub = _FakeMsgHub()
    adapter = WeChatAdapter(
        WeChatConfig(enabled=True),
        hub,  # type: ignore[arg-type]
        state_store=_FakeStateStore(_state()),
        api_client=_FakeIlinkClient(),
    )
    adapter._state = _state()  # noqa: SLF001

    await adapter._handle_inbound_message({  # noqa: SLF001
        "message_id": 102,
        "from_user_id": "wx-user-2",
        "group_id": "wx-group-1",
        "message_type": 1,
        "context_token": "ctx-2",
        "item_list": [{"type": 1, "text_item": {"text": "群消息"}}],
    })

    assert hub.messages == []


async def test_handle_inbound_non_text_message_replies_with_text_only_notice() -> None:
    client = _FakeIlinkClient()
    adapter = WeChatAdapter(
        WeChatConfig(enabled=True),
        _FakeMsgHub(),  # type: ignore[arg-type]
        state_store=_FakeStateStore(_state()),
        api_client=client,
    )
    adapter._state = _state()  # noqa: SLF001
    adapter._context_tokens["wechat:acc-1:wx-user-3"] = "ctx-3"  # noqa: SLF001

    await adapter._handle_inbound_message({  # noqa: SLF001
        "message_id": 103,
        "from_user_id": "wx-user-3",
        "message_type": 1,
        "context_token": "ctx-3",
        "item_list": [{"type": 2}],
    })

    assert client.sent_messages == [{
        "bot_token": "bot-token",
        "to_user_id": "wx-user-3",
        "text": _TEXT_ONLY_REPLY,
        "context_token": "ctx-3",
        "base_url": "https://ilinkai.weixin.qq.com",
    }]


async def test_send_message_uses_cached_context_token() -> None:
    client = _FakeIlinkClient()
    adapter = WeChatAdapter(
        WeChatConfig(enabled=True),
        _FakeMsgHub(),  # type: ignore[arg-type]
        state_store=_FakeStateStore(_state()),
        api_client=client,
    )
    adapter._state = _state()  # noqa: SLF001
    adapter._context_tokens["wechat:acc-1:wx-user-4"] = "ctx-4"  # noqa: SLF001

    await adapter.send_message("wechat:acc-1:wx-user-4", MessageContent(text="reply"))

    assert client.sent_messages[0]["context_token"] == "ctx-4"
    assert client.sent_messages[0]["text"] == "reply"


async def test_send_message_without_context_token_raises_explicit_error() -> None:
    adapter = WeChatAdapter(
        WeChatConfig(enabled=True),
        _FakeMsgHub(),  # type: ignore[arg-type]
        state_store=_FakeStateStore(_state()),
        api_client=_FakeIlinkClient(),
    )
    adapter._state = _state()  # noqa: SLF001

    with pytest.raises(RuntimeError, match=_PROACTIVE_SEND_UNSUPPORTED):
        await adapter.send_message("wechat:acc-1:wx-user-5", MessageContent(text="reply"))


async def test_poll_loop_retries_after_failure() -> None:
    client = _FakeIlinkClient()
    client.fail_first_poll = True
    adapter = WeChatAdapter(
        WeChatConfig(enabled=True, poll_interval=0.01, max_backoff=0.01),
        _FakeMsgHub(),  # type: ignore[arg-type]
        state_store=_FakeStateStore(_state()),
        api_client=client,
    )
    client._adapter = adapter

    await adapter.start()
    await asyncio.sleep(0.05)
    await adapter.stop()

    assert client.get_updates_calls >= 2
