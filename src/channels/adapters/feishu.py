"""Feishu (Lark) platform adapter."""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any

from src.channels.adapters.feishu_api import FEISHU_MESSAGES_PATH, FeishuApiClient
from src.channels.adapters.feishu_security import (
    FeishuWebhookError,
    decode_callback_body,
    extract_verification_token,
    verify_callback_signature,
)
from src.channels.types import MessageContent, UnifiedMessage
from src.core.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import Mapping

    from src.channels.hub import MsgHub
    from src.core.config import FeishuConfig

logger = get_logger(__name__)


class FeishuAdapter:
    """Feishu bot adapter using Open Platform REST API."""

    def __init__(
        self,
        config: FeishuConfig,
        msg_hub: MsgHub,
        *,
        api_client: FeishuApiClient | None = None,
    ) -> None:
        self.config = config
        self.msg_hub = msg_hub
        self._api = api_client or FeishuApiClient(config)
        logger.info("feishu.init")

    @property
    def api_client(self) -> FeishuApiClient:
        return self._api

    async def start(self) -> None:
        """Create the HTTP client and fetch the initial tenant token."""
        await self._api.start()
        logger.info("feishu.started")

    async def stop(self) -> None:
        """Stop the adapter and release resources."""
        await self._api.stop()
        logger.info("feishu.stopped")

    async def process_callback(
        self,
        payload: bytes,
        headers: Mapping[str, str],
    ) -> dict[str, Any]:
        """Validate, decrypt, and process a Feishu callback payload."""
        body, encrypted = decode_callback_body(payload, self.config.encrypt_key)
        self._verify_token(body)
        if "challenge" in body:
            logger.info("feishu.url_verification", encrypted=encrypted)
            return {"challenge": body["challenge"]}
        if encrypted:
            verify_callback_signature(payload, headers, self.config.encrypt_key)
        return await self.process_event(body)

    async def process_event(self, body: dict[str, Any]) -> dict[str, Any]:
        """Process a parsed Feishu event body."""
        if "challenge" in body:
            logger.info("feishu.url_verification", encrypted=False)
            return {"challenge": body["challenge"]}
        event_type = body.get("header", {}).get("event_type", "")
        if event_type == "im.message.receive_v1":
            await self._handle_message_event(body.get("event", {}))
        else:
            logger.debug("feishu.event_ignored", event_type=event_type)
        return {"code": 0, "msg": "ok"}

    async def _handle_message_event(self, event: dict[str, Any]) -> None:
        """Convert a Feishu message event into a unified message."""
        sender = event.get("sender", {}).get("sender_id", {})
        message = event.get("message", {})
        await self._handle_incoming_message(
            sender_id=sender.get("open_id", "unknown"),
            message_id=message.get("message_id", ""),
            chat_id=message.get("chat_id", ""),
            message_type=message.get("message_type", ""),
            raw_content=message.get("content", "{}"),
        )

    async def _handle_incoming_message(
        self,
        *,
        sender_id: str,
        message_id: str,
        chat_id: str,
        message_type: str,
        raw_content: str,
    ) -> None:
        """Normalize and publish a Feishu text message."""
        if message_type != "text":
            logger.debug(
                "feishu.unsupported_msg_type",
                msg_type=message_type,
                msg_id=message_id,
            )
            return
        try:
            content_data = json.loads(raw_content)
        except (json.JSONDecodeError, TypeError):
            logger.warning("feishu.message_parse_failed", msg_id=message_id)
            return
        text = self._strip_mentions(content_data.get("text", ""))
        if not text:
            return
        unified = UnifiedMessage(
            id=message_id,
            platform="feishu",
            sender_id=sender_id,
            conversation_id=chat_id,
            content=MessageContent(text=text),
        )
        logger.info(
            "feishu.message_received",
            sender_id=unified.sender_id,
            chat_id=unified.conversation_id,
            text_length=len(text),
        )
        await self.msg_hub.handle_incoming(unified)

    async def send_message(self, chat_id: str, content: MessageContent) -> None:
        """Send a message to a Feishu chat."""
        if not content.text:
            return
        if self._should_use_card(content.text):
            await self._send_card(chat_id, content.text)
            return
        await self._send_text(chat_id, content.text)

    async def _send_text(self, chat_id: str, text: str) -> None:
        payload = {
            "receive_id": chat_id,
            "msg_type": "text",
            "content": json.dumps({"text": text}, ensure_ascii=False),
        }
        await self._send_api_message(payload)

    async def _send_card(self, chat_id: str, text: str) -> None:
        payload = {
            "receive_id": chat_id,
            "msg_type": "interactive",
            "content": json.dumps(self._build_card(text), ensure_ascii=False),
        }
        await self._send_api_message(payload)

    async def _send_api_message(self, payload: dict[str, Any]) -> None:
        result = await self._api.request(
            "POST",
            FEISHU_MESSAGES_PATH,
            params={"receive_id_type": "chat_id"},
            json=payload,
        )
        if result.get("code") == 0:
            return
        raise RuntimeError(self._api.format_api_error(FEISHU_MESSAGES_PATH, result))

    def _verify_token(self, body: Mapping[str, Any]) -> None:
        expected = self.config.verification_token
        if not expected:
            raise FeishuWebhookError(
                "FEISHU_VERIFICATION_TOKEN is not configured.",
                status_code=503,
            )
        token = extract_verification_token(body)
        if token != expected:
            raise FeishuWebhookError("Invalid Feishu verification token.", status_code=403)

    @staticmethod
    def _should_use_card(text: str) -> bool:
        rich_indicators = ["```", "**", "##", "| ", "- ", "1. "]
        return any(indicator in text for indicator in rich_indicators)

    @staticmethod
    def _build_card(text: str) -> dict[str, Any]:
        return {
            "config": {"wide_screen_mode": True},
            "elements": [
                {
                    "tag": "div",
                    "text": {"tag": "lark_md", "content": text},
                }
            ],
        }

    @staticmethod
    def _strip_mentions(text: str) -> str:
        return re.sub(r"@_\w+\s*", "", text).strip()
