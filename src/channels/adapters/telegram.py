"""Telegram platform adapter.

Converts between Telegram Bot API messages and UnifiedMessage format.
Supports polling mode (Phase 1) and webhook mode (Phase 5).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters

from src.channels.models import MessageContent, UnifiedMessage
from src.platform.logging import get_logger

if TYPE_CHECKING:
    from telegram import Update

    from src.channels.hub import MsgHub
    from src.platform.config import TelegramConfig

logger = get_logger(__name__)


class TelegramAdapter:
    """Telegram bot adapter using python-telegram-bot."""

    def __init__(self, config: TelegramConfig, msg_hub: MsgHub) -> None:
        self.config = config
        self.msg_hub = msg_hub
        self.app = ApplicationBuilder().token(config.bot_token).build()

        # Register message handler
        self.app.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self._on_message)
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

    async def _on_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle incoming Telegram message."""
        if not update.message or not update.message.text:
            return

        tg_msg = update.message
        sender_id = str(tg_msg.from_user.id) if tg_msg.from_user else "unknown"

        # Access control: if allowed_user_ids is set, check sender
        if self.config.allowed_user_ids and int(sender_id) not in self.config.allowed_user_ids:
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

    async def send_message(self, chat_id: str, content: MessageContent) -> None:
        """Send a message back to Telegram."""
        if content.text:
            # Split long messages (Telegram limit: 4096 chars)
            text = content.text
            while text:
                chunk = text[:4096]
                text = text[4096:]
                await self.app.bot.send_message(
                    chat_id=int(chat_id),
                    text=chunk,
                )

        for attachment in content.attachments:
            if attachment.type == "image" and isinstance(attachment.data, bytes):
                await self.app.bot.send_photo(chat_id=int(chat_id), photo=attachment.data)
            elif attachment.type == "file" and isinstance(attachment.data, bytes):
                await self.app.bot.send_document(
                    chat_id=int(chat_id),
                    document=attachment.data,
                    filename=attachment.filename,
                )
