from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from src.channels.adapters.feishu_long_connection import FeishuLongConnectionAdapter
from src.core.config import FeishuConfig


def _set_feishu_env(monkeypatch: Any) -> None:
    monkeypatch.setenv("FEISHU_APP_ID", "cli_test")
    monkeypatch.setenv("FEISHU_APP_SECRET", "secret_test")


class _FakeMsgHub:
    def __init__(self) -> None:
        self.messages: list[Any] = []

    async def handle_incoming(self, message: Any) -> None:
        self.messages.append(message)


async def test_handle_sdk_message_publishes_text_message(monkeypatch: Any) -> None:
    _set_feishu_env(monkeypatch)
    hub = _FakeMsgHub()
    adapter = FeishuLongConnectionAdapter(
        FeishuConfig(enabled=True, mode="long_connection"),
        hub,  # type: ignore[arg-type]
    )
    event = SimpleNamespace(
        sender=SimpleNamespace(
            sender_id=SimpleNamespace(open_id="ou_long"),
        ),
        message=SimpleNamespace(
            message_id="om_long",
            chat_id="oc_long",
            message_type="text",
            content='{"text":"hello from long connection"}',
        ),
    )

    await adapter._handle_sdk_message(SimpleNamespace(event=event))

    assert len(hub.messages) == 1
    message = hub.messages[0]
    assert message.platform == "feishu"
    assert message.sender_id == "ou_long"
    assert message.conversation_id == "oc_long"
    assert message.content.text == "hello from long connection"


async def test_handle_sdk_message_ignores_missing_message(monkeypatch: Any) -> None:
    _set_feishu_env(monkeypatch)
    hub = _FakeMsgHub()
    adapter = FeishuLongConnectionAdapter(
        FeishuConfig(enabled=True, mode="long_connection"),
        hub,  # type: ignore[arg-type]
    )

    await adapter._handle_sdk_message(
        SimpleNamespace(event=SimpleNamespace(sender=None, message=None)),
    )

    assert hub.messages == []
