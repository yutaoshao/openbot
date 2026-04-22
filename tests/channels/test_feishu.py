"""Tests for the Feishu adapter."""

from __future__ import annotations

import json
from types import MethodType
from typing import Any

from src.channels.adapters.feishu import FeishuAdapter
from src.channels.hub import MsgHub
from src.channels.types import MessageContent
from src.core.config import FeishuConfig
from src.infrastructure.event_bus import EventBus


def _set_feishu_env(monkeypatch: Any) -> None:
    monkeypatch.setenv("FEISHU_APP_ID", "cli_test")
    monkeypatch.setenv("FEISHU_APP_SECRET", "secret_test")
    monkeypatch.setenv("FEISHU_VERIFICATION_TOKEN", "verify_test")
    monkeypatch.setenv("FEISHU_ENCRYPT_KEY", "encrypt_test")


class _FakeMsgHub:
    def __init__(self) -> None:
        self.messages: list[Any] = []

    async def handle_incoming(self, message: Any) -> None:
        self.messages.append(message)


class TestStripMentions:
    def test_strips_user_mentions(self) -> None:
        assert FeishuAdapter._strip_mentions("@_user_1 hello") == "hello"

    def test_strips_all_mention(self) -> None:
        assert FeishuAdapter._strip_mentions("@_all check this") == "check this"

    def test_no_mention(self) -> None:
        assert FeishuAdapter._strip_mentions("plain text") == "plain text"

    def test_multiple_mentions(self) -> None:
        assert FeishuAdapter._strip_mentions("@_user_1 @_user_2 hi") == "hi"


class TestShouldUseCard:
    def test_plain_text_no_card(self) -> None:
        assert FeishuAdapter._should_use_card("just a simple reply") is False

    def test_code_block_triggers_card(self) -> None:
        assert FeishuAdapter._should_use_card("here: ```code```") is True

    def test_bold_triggers_card(self) -> None:
        assert FeishuAdapter._should_use_card("**important**") is True

    def test_table_triggers_card(self) -> None:
        assert FeishuAdapter._should_use_card("| col1 | col2 |") is True


class TestBuildCard:
    def test_card_structure(self) -> None:
        card = FeishuAdapter._build_card("hello world")
        assert "config" in card
        assert "elements" in card
        assert card["config"]["wide_screen_mode"] is True
        assert len(card["elements"]) == 1
        assert card["elements"][0]["tag"] == "div"
        assert card["elements"][0]["text"]["tag"] == "lark_md"
        assert card["elements"][0]["text"]["content"] == "hello world"


async def test_process_event_returns_challenge(monkeypatch: Any) -> None:
    _set_feishu_env(monkeypatch)
    adapter = FeishuAdapter(FeishuConfig(enabled=True), _FakeMsgHub())  # type: ignore[arg-type]

    result = await adapter.process_event({"challenge": "challenge_test", "token": "verify_test"})

    assert result == {"challenge": "challenge_test"}


async def test_process_event_routes_text_message_to_msg_hub(monkeypatch: Any) -> None:
    _set_feishu_env(monkeypatch)
    hub = _FakeMsgHub()
    adapter = FeishuAdapter(FeishuConfig(enabled=True), hub)  # type: ignore[arg-type]

    await adapter.process_event(
        {
            "header": {
                "event_type": "im.message.receive_v1",
                "token": "verify_test",
            },
            "event": {
                "sender": {"sender_id": {"open_id": "ou_test"}},
                "message": {
                    "message_id": "om_123",
                    "chat_id": "oc_456",
                    "message_type": "text",
                    "content": json.dumps({"text": "@_user_1 hello"}),
                },
            },
        }
    )

    assert len(hub.messages) == 1
    message = hub.messages[0]
    assert message.platform == "feishu"
    assert message.sender_id == "ou_test"
    assert message.conversation_id == "oc_456"
    assert message.content.text == "hello"


async def test_process_event_ignores_non_text_messages(monkeypatch: Any) -> None:
    _set_feishu_env(monkeypatch)
    hub = _FakeMsgHub()
    adapter = FeishuAdapter(FeishuConfig(enabled=True), hub)  # type: ignore[arg-type]

    await adapter.process_event(
        {
            "header": {"event_type": "im.message.receive_v1", "token": "verify_test"},
            "event": {
                "sender": {"sender_id": {"open_id": "ou_test"}},
                "message": {
                    "message_id": "om_123",
                    "chat_id": "oc_456",
                    "message_type": "image",
                    "content": "{}",
                },
            },
        }
    )

    assert hub.messages == []


async def test_send_message_uses_text_path_for_plain_text(monkeypatch: Any) -> None:
    _set_feishu_env(monkeypatch)
    adapter = FeishuAdapter(FeishuConfig(enabled=True), _FakeMsgHub())  # type: ignore[arg-type]
    calls: list[tuple[str, str]] = []

    async def fake_send_text(self: FeishuAdapter, chat_id: str, text: str) -> None:
        calls.append((chat_id, text))

    async def fake_send_card(self: FeishuAdapter, chat_id: str, text: str) -> None:
        raise AssertionError("rich card path should not be used")

    adapter._send_text = MethodType(fake_send_text, adapter)
    adapter._send_card = MethodType(fake_send_card, adapter)

    await adapter.send_message("oc_1", MessageContent(text="plain"))

    assert calls == [("oc_1", "plain")]


async def test_send_message_uses_card_path_for_rich_text(monkeypatch: Any) -> None:
    _set_feishu_env(monkeypatch)
    adapter = FeishuAdapter(FeishuConfig(enabled=True), _FakeMsgHub())  # type: ignore[arg-type]
    calls: list[tuple[str, str]] = []

    async def fake_send_text(self: FeishuAdapter, chat_id: str, text: str) -> None:
        raise AssertionError("plain text path should not be used")

    async def fake_send_card(self: FeishuAdapter, chat_id: str, text: str) -> None:
        calls.append((chat_id, text))

    adapter._send_text = MethodType(fake_send_text, adapter)
    adapter._send_card = MethodType(fake_send_card, adapter)

    await adapter.send_message("oc_1", MessageContent(text="## heading"))

    assert calls == [("oc_1", "## heading")]


async def test_msg_hub_routes_agent_response_back_to_feishu(monkeypatch: Any) -> None:
    _set_feishu_env(monkeypatch)
    event_bus = EventBus()
    hub = MsgHub(event_bus)
    adapter = FeishuAdapter(FeishuConfig(enabled=True), _FakeMsgHub())  # type: ignore[arg-type]
    calls: list[tuple[str, str | None]] = []

    async def fake_send_message(self: FeishuAdapter, chat_id: str, content: MessageContent) -> None:
        calls.append((chat_id, content.text))

    adapter.send_message = MethodType(fake_send_message, adapter)
    hub.register_adapter("feishu", adapter)

    await event_bus.publish(
        "agent.response",
        {
            "platform": "feishu",
            "target_id": "oc_1",
            "content": MessageContent(text="reply"),
        },
    )

    assert calls == [("oc_1", "reply")]
