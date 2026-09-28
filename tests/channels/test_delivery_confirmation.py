"""A memory delivery is confirmed only after a final transport send succeeds."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.application.message_dispatch import handle_non_streaming, handle_streaming
from src.channels.adapters.web import WebAdapter
from src.channels.hub import MsgHub
from src.channels.types import MessageContent, StreamingDelivery
from src.infrastructure.event_bus import EventBus
from src.infrastructure.model_types import StreamChunk


async def _chunks():
    yield StreamChunk(type="text", text="final answer")
    yield StreamChunk(type="done")


class _Socket:
    def __init__(self, fail_on: str = "") -> None:
        self.events: list[dict] = []
        self.fail_on = fail_on

    async def send_json(self, event: dict) -> None:
        if event.get("chunk_type") == self.fail_on:
            raise ConnectionError("socket disconnected")
        self.events.append(event)


async def test_web_stream_only_confirms_final_frame_after_success() -> None:
    adapter = WebAdapter()
    assert not (await adapter.send_streaming("absent", _chunks())).delivered

    broken = _Socket("done")
    await adapter.register("broken", broken)  # type: ignore[arg-type]
    result = await adapter.send_streaming("broken", _chunks())
    assert broken.events[0]["text"] == "final answer"
    assert not result.delivered

    good = _Socket()
    await adapter.register("good", good)  # type: ignore[arg-type]
    result = await adapter.send_streaming("good", _chunks())
    assert result == StreamingDelivery(True, "final answer")
    assert good.events[-1]["chunk_type"] == "done"


async def test_hub_confirmation_requires_adapter_delivery() -> None:
    hub = MsgHub(EventBus())
    confirmed: list[tuple[str, str, str]] = []

    async def confirm(cid: str, text: str, delivery_id: str) -> None:
        confirmed.append((cid, text, delivery_id))

    socket = _Socket()
    adapter = WebAdapter()
    hub.register_adapter("web", adapter)
    payload = {
        "platform": "web",
        "target_id": "conv",
        "content": MessageContent(text="answer"),
        "delivery_id": "outbound-1",
        "confirm_delivery": confirm,
    }
    await hub.event_bus.publish("agent.response", payload)
    assert confirmed == []

    await adapter.register("conv", socket)  # type: ignore[arg-type]
    await hub.event_bus.publish("agent.response", payload)
    assert confirmed == [("conv", "answer", "outbound-1")]

    socket.fail_on = "message"

    async def fail_send(event: dict) -> None:
        raise ConnectionError("socket disconnected")

    socket.send_json = fail_send  # type: ignore[method-assign]
    await hub.event_bus.publish("agent.response", payload)
    assert len(confirmed) == 1


async def test_stream_dispatch_only_confirms_delivered_final_text() -> None:
    confirmed: list[tuple[str, str, str]] = []

    class Agent:
        def run_stream(self, **kwargs):
            return _chunks()

        async def confirm_delivery(self, cid: str, text: str, delivery_id: str) -> None:
            confirmed.append((cid, text, delivery_id))

    class Adapter:
        delivered = False

        async def send_streaming(self, cid: str, stream):
            text = "".join([chunk.text async for chunk in stream if chunk.type == "text"])
            return StreamingDelivery(self.delivered, text, "remote-message-1")

    adapter = Adapter()
    events = []

    class Bus:
        async def publish(self, name: str, payload: dict) -> None:
            events.append((name, payload))

    app = SimpleNamespace(agent=Agent(), event_bus=Bus())
    message = SimpleNamespace(
        content=MessageContent(text="question"),
        conversation_id="conv",
        platform="web",
        user_id="user",
        timestamp=None,
        id="inbound",
        sender_id="user",
    )
    await handle_streaming(app, message, adapter)  # type: ignore[arg-type]
    assert confirmed == []
    adapter.delivered = True
    await handle_streaming(app, message, adapter)  # type: ignore[arg-type]
    assert confirmed == [("conv", "final answer", "remote-message-1")]


async def test_non_stream_dispatch_waits_for_hub_send() -> None:
    confirmed: list[tuple[str, str, str]] = []

    class Agent:
        async def run(self, **kwargs):
            return SimpleNamespace(content="answer", latency_ms=1, tokens_in=1, tokens_out=1)

        async def confirm_delivery(self, cid: str, text: str, delivery_id: str) -> None:
            confirmed.append((cid, text, delivery_id))

    bus = EventBus()
    hub = MsgHub(bus)
    app = SimpleNamespace(agent=Agent(), event_bus=bus)
    message = SimpleNamespace(
        content=MessageContent(text="question"),
        conversation_id="conv",
        platform="web",
        user_id="user",
        timestamp=None,
        id="inbound",
        sender_id="user",
    )
    hub.register_adapter("web", WebAdapter())
    await handle_non_streaming(app, message)
    assert confirmed == []

    socket = _Socket()
    await hub.get_adapter("web").register("conv", socket)  # type: ignore[arg-type]
    await handle_non_streaming(app, message)
    assert len(confirmed) == 1
    assert confirmed[0][:2] == ("conv", "answer")
    assert confirmed[0][2]


@pytest.mark.parametrize("raise_send", [False, True])
async def test_telegram_draft_never_confirms_without_final_send(raise_send: bool) -> None:
    from src.channels.adapters.telegram import TelegramAdapter

    adapter = object.__new__(TelegramAdapter)
    adapter._stream_throttle = 0
    drafts: list[str] = []

    async def draft(chat_id: str, draft_id: int, text: str) -> bool:
        drafts.append(text)
        return True

    async def send_final(chat_id: str, text: str, parse_mode: str | None = None) -> str:
        if raise_send:
            raise ConnectionError("final failed")
        return "tg-77"

    adapter._update_draft = draft  # type: ignore[method-assign]
    adapter._send_final_message = send_final  # type: ignore[method-assign]
    if raise_send:
        with pytest.raises(ConnectionError, match="final failed"):
            await adapter.send_streaming("123", _chunks())
    else:
        assert await adapter.send_streaming("123", _chunks()) == StreamingDelivery(
            True, "final answer", "tg-77"
        )
    assert drafts
