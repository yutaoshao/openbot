"""Messaging/runtime helpers for Application."""

from __future__ import annotations

from typing import Any

from src.channels.types import MessageContent, StreamingAdapter
from src.core.logging import get_logger
from src.core.trace import trace_scope

logger = get_logger(__name__)


async def on_message_receive(app: Any, data: dict[str, Any]) -> None:
    """Handle incoming platform messages."""
    message = data["message"]
    input_text = message.content.text
    if not input_text:
        return

    message.user_id = await app.identity_service.resolve_user_id(
        platform=message.platform,
        platform_user_id=message.sender_id,
        conversation_id=message.conversation_id,
        user_id=message.user_id,
    )
    with trace_scope(interaction_id=message.conversation_id, platform=message.platform):
        logger.info(
            "task_received",
            surface="contextual",
            sender=message.sender_id,
            text_length=len(input_text),
        )
        adapter = app.msg_hub.get_adapter(message.platform)
        try:
            async with app.execution_coordinator.serialize(
                message.user_id or message.conversation_id,
            ) as queue_wait_ms:
                await app.event_bus.publish(
                    "harness.queue_wait",
                    {
                        "conversation_id": message.conversation_id,
                        "platform": message.platform,
                        "user_id": message.user_id or "",
                        "queue_wait_ms": int(queue_wait_ms),
                    },
                )
                use_streaming = isinstance(adapter, StreamingAdapter) and (
                    message.platform != "telegram" or app.config.telegram.enable_streaming
                )
                if use_streaming:
                    await handle_streaming(app, message, adapter)
                else:
                    await handle_non_streaming(app, message)
        except Exception:
            logger.exception(
                "task_failed",
                surface="operational",
                reason="unhandled_exception",
            )
            await app.event_bus.publish(
                "agent.response",
                {
                    "platform": message.platform,
                    "target_id": message.conversation_id,
                    "content": MessageContent(
                        text="Sorry, an error occurred. Please try again.",
                    ),
                },
            )


async def handle_streaming(app: Any, message: Any, adapter: StreamingAdapter) -> None:
    """Streaming path: Agent.run_stream() -> adapter.send_streaming()."""
    import time

    start = time.monotonic()
    stream = app.agent.run_stream(
        input_text=message.content.text,
        conversation_id=message.conversation_id,
        platform=message.platform,
        user_id=message.user_id or "",
    )
    await adapter.send_streaming(message.conversation_id, stream)
    latency_ms = int((time.monotonic() - start) * 1000)
    await app.event_bus.publish(
        "agent.metrics",
        {
            "platform": message.platform,
            "conversation_id": message.conversation_id,
            "latency_ms": latency_ms,
        },
    )
    logger.info(
        "task_finished",
        surface="operational",
        latency_ms=latency_ms,
        mode="streaming",
    )


async def handle_non_streaming(app: Any, message: Any) -> None:
    """Non-streaming path: Agent.run() -> event bus -> MsgHub."""
    result = await app.agent.run(
        input_text=message.content.text,
        conversation_id=message.conversation_id,
        platform=message.platform,
        user_id=message.user_id or "",
    )
    await app.event_bus.publish(
        "agent.response",
        {
            "platform": message.platform,
            "target_id": message.conversation_id,
            "content": MessageContent(text=result.content),
            "latency_ms": result.latency_ms,
            "tokens_in": result.tokens_in,
            "tokens_out": result.tokens_out,
        },
    )
    logger.info(
        "task_finished",
        surface="operational",
        latency_ms=result.latency_ms,
        token_in=result.tokens_in,
        token_out=result.tokens_out,
        mode="non_streaming",
    )
