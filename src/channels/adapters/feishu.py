"""Feishu (Lark) platform adapter.

Integrates with Feishu Open Platform via:
- Event subscription webhook for incoming messages
- REST API for outgoing messages (text + interactive card)
- Tenant access token management with auto-refresh
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

import httpx

from src.channels.types import MessageContent, UnifiedMessage
from src.core.logging import get_logger

if TYPE_CHECKING:
    from src.channels.hub import MsgHub
    from src.core.config import FeishuConfig

logger = get_logger(__name__)

_FEISHU_API = "https://open.feishu.cn/open-apis"

# Token refresh buffer (refresh 5 minutes before expiry)
_TOKEN_REFRESH_BUFFER = 300


class FeishuAdapter:
    """Feishu bot adapter using Open Platform REST API."""

    def __init__(self, config: FeishuConfig, msg_hub: MsgHub) -> None:
        self.config = config
        self.msg_hub = msg_hub
        self._tenant_token: str = ""
        self._token_expires_at: float = 0.0
        self._client: httpx.AsyncClient | None = None

        logger.info("feishu.init")

    async def start(self) -> None:
        """Start the adapter (create HTTP client, fetch initial token)."""
        self._client = httpx.AsyncClient(timeout=30)
        await self._refresh_token()
        logger.info("feishu.started")

    async def stop(self) -> None:
        """Stop the adapter and release resources."""
        if self._client:
            await self._client.aclose()
            self._client = None
        logger.info("feishu.stopped")

    # ------------------------------------------------------------------
    # Incoming: webhook event processing
    # ------------------------------------------------------------------

    async def process_event(self, body: dict[str, Any]) -> dict[str, Any]:
        """Process a Feishu event callback.

        Returns the JSON response to send back to Feishu.
        Handles: URL verification challenge, message events.
        """
        # URL verification (Feishu sends this when registering webhook)
        if "challenge" in body:
            logger.info("feishu.url_verification")
            return {"challenge": body["challenge"]}

        # Schema v2 event
        header = body.get("header", {})
        event_type = header.get("event_type", "")

        if event_type == "im.message.receive_v1":
            await self._handle_message_event(body.get("event", {}))
        else:
            logger.debug("feishu.event_ignored", event_type=event_type)

        return {"code": 0, "msg": "ok"}

    async def _handle_message_event(self, event: dict[str, Any]) -> None:
        """Convert a Feishu message event to UnifiedMessage."""
        sender = event.get("sender", {}).get("sender_id", {})
        sender_id = sender.get("open_id", "unknown")
        message = event.get("message", {})
        msg_id = message.get("message_id", "")
        chat_id = message.get("chat_id", "")
        msg_type = message.get("message_type", "")

        # Only handle text messages for now
        if msg_type != "text":
            logger.debug(
                "feishu.unsupported_msg_type",
                msg_type=msg_type,
                msg_id=msg_id,
            )
            return

        import json

        try:
            content_data = json.loads(message.get("content", "{}"))
            text = content_data.get("text", "")
        except (json.JSONDecodeError, TypeError):
            text = ""

        if not text:
            return

        # Strip @bot mentions (Feishu includes @_user_1 in text)
        text = self._strip_mentions(text)
        if not text:
            return

        unified = UnifiedMessage(
            id=msg_id,
            platform="feishu",
            sender_id=sender_id,
            conversation_id=chat_id,
            content=MessageContent(text=text),
        )

        logger.info(
            "feishu.message_received",
            sender_id=sender_id,
            chat_id=chat_id,
            text_length=len(text),
        )

        await self.msg_hub.handle_incoming(unified)

    # ------------------------------------------------------------------
    # Outgoing: send messages
    # ------------------------------------------------------------------

    async def send_message(self, chat_id: str, content: MessageContent) -> None:
        """Send a message to a Feishu chat."""
        if not content.text:
            return

        # Use interactive card for rich content, plain text for simple
        if self._should_use_card(content.text):
            await self._send_card(chat_id, content.text)
        else:
            await self._send_text(chat_id, content.text)

    async def _send_text(self, chat_id: str, text: str) -> None:
        """Send a plain text message."""
        import json

        await self._api_request(
            "POST",
            "/im/v1/messages",
            params={"receive_id_type": "chat_id"},
            json={
                "receive_id": chat_id,
                "msg_type": "text",
                "content": json.dumps({"text": text}, ensure_ascii=False),
            },
        )

    async def _send_card(self, chat_id: str, text: str) -> None:
        """Send an interactive card message with markdown-like formatting."""
        import json

        card = self._build_card(text)
        await self._api_request(
            "POST",
            "/im/v1/messages",
            params={"receive_id_type": "chat_id"},
            json={
                "receive_id": chat_id,
                "msg_type": "interactive",
                "content": json.dumps(card, ensure_ascii=False),
            },
        )

    # ------------------------------------------------------------------
    # Card builder
    # ------------------------------------------------------------------

    @staticmethod
    def _should_use_card(text: str) -> bool:
        """Decide whether to use card format (for rich content)."""
        rich_indicators = ["```", "**", "##", "| ", "- ", "1. "]
        return any(ind in text for ind in rich_indicators)

    @staticmethod
    def _build_card(text: str) -> dict[str, Any]:
        """Build a Feishu interactive card from markdown text.

        Feishu cards support a subset of markdown in ``div`` elements
        with ``lark_md`` tag.
        """
        # Split into sections by double newline or headers
        elements: list[dict[str, Any]] = []

        # Use Feishu's markdown element directly
        # Feishu lark_md supports: bold, italic, links, code, strikethrough
        elements.append({
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": text,
            },
        })

        return {
            "config": {"wide_screen_mode": True},
            "elements": elements,
        }

    # ------------------------------------------------------------------
    # Token management
    # ------------------------------------------------------------------

    async def _refresh_token(self) -> None:
        """Fetch or refresh the tenant access token."""
        if not self._client:
            return

        try:
            resp = await self._client.post(
                f"{_FEISHU_API}/auth/v3/tenant_access_token/internal",
                json={
                    "app_id": self.config.app_id,
                    "app_secret": self.config.app_secret,
                },
            )
            resp.raise_for_status()
            data = resp.json()

            if data.get("code") != 0:
                logger.error(
                    "feishu.token_error",
                    code=data.get("code"),
                    msg=data.get("msg"),
                )
                return

            self._tenant_token = data.get("tenant_access_token", "")
            expire = data.get("expire", 7200)
            self._token_expires_at = time.monotonic() + expire - _TOKEN_REFRESH_BUFFER

            logger.info("feishu.token_refreshed", expires_in=expire)
        except Exception:
            logger.exception("feishu.token_refresh_failed")

    async def _ensure_token(self) -> str:
        """Ensure we have a valid token, refreshing if needed."""
        if time.monotonic() >= self._token_expires_at:
            await self._refresh_token()
        return self._tenant_token

    # ------------------------------------------------------------------
    # HTTP helper
    # ------------------------------------------------------------------

    async def _api_request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Make an authenticated Feishu API request."""
        if not self._client:
            logger.error("feishu.client_not_initialized")
            return {"code": -1, "msg": "Client not initialized"}

        token = await self._ensure_token()
        headers = {"Authorization": f"Bearer {token}"}

        try:
            resp = await self._client.request(
                method,
                f"{_FEISHU_API}{path}",
                headers=headers,
                params=params,
                json=json,
            )
            resp.raise_for_status()
            data = resp.json()

            if data.get("code") != 0:
                logger.warning(
                    "feishu.api_error",
                    path=path,
                    code=data.get("code"),
                    msg=data.get("msg"),
                )

            return data
        except httpx.HTTPStatusError as e:
            logger.error(
                "feishu.api_http_error",
                path=path,
                status=e.response.status_code,
            )
            return {"code": e.response.status_code, "msg": str(e)}
        except Exception as e:
            logger.exception("feishu.api_request_failed", path=path)
            return {"code": -1, "msg": str(e)}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _strip_mentions(text: str) -> str:
        """Remove @bot mentions from message text."""
        import re

        # Feishu mentions look like @_user_1 or @_all
        return re.sub(r"@_\w+\s*", "", text).strip()
