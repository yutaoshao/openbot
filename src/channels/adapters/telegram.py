"""Telegram core adapter.

Converts between Telegram Bot API messages and UnifiedMessage format.
Supports polling mode (Phase 1) and webhook mode (Phase 5).
"""

from __future__ import annotations

import random
import time
from typing import TYPE_CHECKING

from telegram.error import TelegramError
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters

from src.channels.markdown import md_to_telegram_html
from src.channels.types import MessageContent, UnifiedMessage
from src.core.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from telegram import Update

    from src.channels.hub import MsgHub
    from src.core.config import TelegramConfig
    from src.infrastructure.model_gateway import StreamChunk

logger = get_logger(__name__)

# Telegram message length limit
_TG_MAX_LEN = 4096

# Max consecutive draft failures before degrading
_MAX_DRAFT_FAILURES = 3


class TelegramAdapter:
    """Telegram bot adapter using python-telegram-bot."""

    def __init__(self, config: TelegramConfig, msg_hub: MsgHub) -> None:
        self.config = config
        self.msg_hub = msg_hub
        self._stream_throttle = config.stream_throttle
        self.app = ApplicationBuilder().token(config.bot_token).build()

        # Register message handler
        self.app.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self._on_message),
        )

        logger.info("telegram.init", mode=config.mode)

    async def start(self) -> None:
        """Start the Telegram bot in polling mode."""
        logger.info("telegram.starting", mode=self.config.mode)
        await self.app.initialize()
        await self.app.start()

        if self.config.mode == "polling":
            await self.app.updater.start_polling(drop_pending_updates=True)
            logger.info("telegram.polling_started")

    async def stop(self) -> None:
        """Stop the Telegram bot gracefully."""
        logger.info("telegram.stopping")
        if self.app.updater and self.app.updater.running:
            await self.app.updater.stop()
        await self.app.stop()
        await self.app.shutdown()
        logger.info("telegram.stopped")

    # ------------------------------------------------------------------
    # Incoming messages
    # ------------------------------------------------------------------

    async def _on_message(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        """Handle incoming Telegram message."""
        if not update.message or not update.message.text:
            return

        tg_msg = update.message
        sender_id = str(tg_msg.from_user.id) if tg_msg.from_user else "unknown"

        # Access control
        if (
            self.config.allowed_user_ids
            and int(sender_id) not in self.config.allowed_user_ids
        ):
            logger.warning("telegram.unauthorized", sender_id=sender_id)
            return

        unified = UnifiedMessage(
            id=str(tg_msg.message_id),
            platform="telegram",
            sender_id=sender_id,
            conversation_id=str(tg_msg.chat_id),
            content=MessageContent(text=tg_msg.text),
        )

        logger.info(
            "telegram.message_received",
            sender_id=sender_id,
            chat_id=tg_msg.chat_id,
            text_length=len(tg_msg.text),
        )

        await self.msg_hub.handle_incoming(unified)

    # ------------------------------------------------------------------
    # Outgoing: non-streaming
    # ------------------------------------------------------------------

    async def send_message(self, chat_id: str, content: MessageContent) -> None:
        """Send a message back to Telegram (non-streaming)."""
        if content.text:
            await self._send_final_message(chat_id, content.text)

        for attachment in content.attachments:
            if attachment.type == "image" and isinstance(attachment.data, bytes):
                await self.app.bot.send_photo(
                    chat_id=int(chat_id), photo=attachment.data,
                )
            elif attachment.type == "file" and isinstance(attachment.data, bytes):
                await self.app.bot.send_document(
                    chat_id=int(chat_id),
                    document=attachment.data,
                    filename=attachment.filename,
                )

    # ------------------------------------------------------------------
    # Outgoing: streaming via sendMessageDraft
    # ------------------------------------------------------------------

    async def send_streaming(
        self,
        chat_id: str,
        stream: AsyncIterator[StreamChunk],
    ) -> None:
        """Consume a streaming response and deliver via sendMessageDraft.

        Flow: draft -> draft -> ... -> send_message (final).
        """
        draft_id = random.randint(1, 2**31 - 1)
        accumulated = ""
        last_draft_time = 0.0
        consecutive_failures = 0

        async for chunk in stream:
            if chunk.type == "text":
                accumulated += chunk.text
                now = time.monotonic()
                if now - last_draft_time >= self._stream_throttle:
                    if not await self._update_draft(
                        chat_id, draft_id, accumulated,
                    ):
                        consecutive_failures += 1
                        if consecutive_failures >= _MAX_DRAFT_FAILURES:
                            logger.warning(
                                "telegram.draft_degraded",
                                chat_id=chat_id,
                                failures=consecutive_failures,
                            )
                            # Stop drafting; continue consuming stream,
                            # final message will still be sent.
                    else:
                        consecutive_failures = 0
                    last_draft_time = now

            elif chunk.type == "tool_status" and chunk.tool_name:
                # Show tool status in draft
                draft_text = accumulated + f"\n\n... {chunk.tool_name}"
                await self._update_draft(chat_id, draft_id, draft_text)

            elif chunk.type == "done":
                # Metadata collected by Application layer
                pass

        # Send final formatted message
        if accumulated:
            final_html = md_to_telegram_html(accumulated, partial=False)
            await self._send_final_message(
                chat_id, final_html, parse_mode="HTML",
            )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _update_draft(
        self, chat_id: str, draft_id: int, text: str,
    ) -> bool:
        """Send a draft update.  Returns True on success."""
        try:
            html = md_to_telegram_html(text, partial=True)
            await self.app.bot.send_message_draft(
                chat_id=int(chat_id),
                draft_id=draft_id,
                text=html,
                parse_mode="HTML",
            )
            return True
        except TelegramError as e:
            logger.warning(
                "telegram.draft_failed",
                chat_id=chat_id,
                error=str(e),
            )
            return False

    async def _send_final_message(
        self,
        chat_id: str,
        text: str,
        parse_mode: str | None = None,
    ) -> None:
        """Send the final message, splitting if it exceeds Telegram's limit."""
        while text:
            chunk = text[:_TG_MAX_LEN]
            text = text[_TG_MAX_LEN:]
            try:
                await self.app.bot.send_message(
                    chat_id=int(chat_id),
                    text=chunk,
                    parse_mode=parse_mode,
                )
            except TelegramError:
                # If HTML parse fails, retry without parse_mode
                if parse_mode:
                    logger.warning(
                        "telegram.html_parse_failed",
                        chat_id=chat_id,
                        retrying_plain=True,
                    )
                    await self.app.bot.send_message(
                        chat_id=int(chat_id),
                        text=chunk,
                    )
                else:
                    raise
