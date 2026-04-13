"""Feishu long-connection adapter built on the official SDK."""

from __future__ import annotations

import asyncio
import concurrent.futures
import contextlib
import threading
from typing import TYPE_CHECKING, Any

from src.channels.adapters.feishu import FeishuAdapter
from src.core.logging import get_logger

if TYPE_CHECKING:
    from src.channels.hub import MsgHub
    from src.core.config import FeishuConfig

logger = get_logger(__name__)

_START_TIMEOUT_SECONDS = 10
_STOP_TIMEOUT_SECONDS = 10


class FeishuLongConnectionAdapter(FeishuAdapter):
    """Feishu adapter that receives events over the SDK long connection."""

    def __init__(self, config: FeishuConfig, msg_hub: MsgHub) -> None:
        super().__init__(config, msg_hub)
        self._main_loop: asyncio.AbstractEventLoop | None = None
        self._sdk_loop: asyncio.AbstractEventLoop | None = None
        self._sdk_client: Any | None = None
        self._sdk_module: Any | None = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._start_error: BaseException | None = None

    async def start(self) -> None:
        """Start the Feishu API client and SDK long-connection client."""
        await self.api_client.start()
        self._main_loop = asyncio.get_running_loop()
        self._thread = threading.Thread(
            target=self._run_client_thread,
            name="feishu-long-connection",
            daemon=True,
        )
        self._thread.start()
        await asyncio.to_thread(self._ready.wait, _START_TIMEOUT_SECONDS)
        if not self._ready.is_set():
            raise RuntimeError("Feishu long connection did not become ready in time.")
        if self._start_error is not None:
            raise RuntimeError("Failed to start Feishu long connection.") from self._start_error
        logger.info("feishu.long_connection_started")
        logger.info("feishu.started")

    async def stop(self) -> None:
        """Stop the SDK long connection and outbound API client."""
        await self._stop_long_connection()
        await self.api_client.stop()
        logger.info("feishu.stopped")

    def _run_client_thread(self) -> None:
        """Run the blocking SDK client on a dedicated thread-local event loop."""
        try:
            import lark_oapi as lark
            import lark_oapi.ws.client as lark_ws_client_module
        except Exception as exc:  # pragma: no cover - import failure surfaced in start()
            self._start_error = exc
            self._ready.set()
            return

        loop = lark_ws_client_module.loop
        self._sdk_loop = loop
        self._sdk_module = lark_ws_client_module
        handler = self._build_event_handler(lark)
        client = lark.ws.Client(
            self.config.app_id,
            self.config.app_secret,
            event_handler=handler,
            log_level=lark.LogLevel.INFO,
        )
        self._sdk_client = client
        try:
            loop.run_until_complete(client._connect())
            loop.create_task(client._ping_loop())
            self._ready.set()
            logger.info("feishu.long_connection_ready")
            loop.run_forever()
        except BaseException as exc:  # pragma: no cover - runtime failure surfaced via logs
            self._start_error = exc
            self._ready.set()
            logger.exception("feishu.long_connection_failed")
        finally:
            with contextlib.suppress(Exception):
                if client._conn is not None:
                    loop.run_until_complete(client._disconnect())

    def _build_event_handler(self, lark: Any) -> Any:
        """Build the official SDK event handler."""
        return (
            lark.EventDispatcherHandler
            .builder("", "")
            .register_p2_im_message_receive_v1(self._on_sdk_message)
            .build()
        )

    def _on_sdk_message(self, data: Any) -> None:
        """Receive a typed SDK event and forward it into the main app loop."""
        if self._main_loop is None:
            logger.error("feishu.long_connection_missing_main_loop")
            return
        future = asyncio.run_coroutine_threadsafe(
            self._handle_sdk_message(data),
            self._main_loop,
        )
        future.add_done_callback(self._log_sdk_future_error)

    async def _handle_sdk_message(self, data: Any) -> None:
        """Convert the SDK event into the existing Feishu text-message flow."""
        event = getattr(data, "event", None)
        if event is None:
            logger.warning("feishu.long_connection_missing_event")
            return
        sender = getattr(event, "sender", None)
        sender_id = getattr(getattr(sender, "sender_id", None), "open_id", "unknown")
        message = getattr(event, "message", None)
        if message is None:
            logger.warning("feishu.long_connection_missing_message")
            return
        await self._handle_incoming_message(
            sender_id=sender_id,
            message_id=getattr(message, "message_id", ""),
            chat_id=getattr(message, "chat_id", ""),
            message_type=getattr(message, "message_type", ""),
            raw_content=getattr(message, "content", "{}"),
        )

    @staticmethod
    def _log_sdk_future_error(future: concurrent.futures.Future[None]) -> None:
        """Log async failures scheduled from the SDK thread."""
        with contextlib.suppress(concurrent.futures.CancelledError):
            exc = future.exception()
            if exc is not None:
                logger.exception("feishu.long_connection_event_failed", exc_info=exc)

    async def _stop_long_connection(self) -> None:
        """Disconnect the SDK client and stop its loop."""
        if self._sdk_client is not None:
            self._sdk_client._auto_reconnect = False
        if self._sdk_loop is not None and self._sdk_client is not None:
            disconnect = asyncio.run_coroutine_threadsafe(
                self._sdk_client._disconnect(),
                self._sdk_loop,
            )
            with contextlib.suppress(Exception):
                await asyncio.wrap_future(disconnect)
            self._sdk_loop.call_soon_threadsafe(self._sdk_loop.stop)
        if self._thread is not None:
            await asyncio.to_thread(self._thread.join, _STOP_TIMEOUT_SECONDS)
