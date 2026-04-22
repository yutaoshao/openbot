"""WeChat personal-account adapter backed by the iLink polling API."""

from __future__ import annotations

import asyncio
import contextlib
from typing import TYPE_CHECKING, Any

from src.channels.types import MessageContent, UnifiedMessage
from src.core.logging import get_logger

from .wechat_ilink_api import ILinkApiError, WeChatIlinkClient
from .wechat_state import WeChatLoginState, WeChatStateStore

if TYPE_CHECKING:
    from src.channels.hub import MsgHub
    from src.core.config import WeChatConfig

logger = get_logger(__name__)

_TEXT_ONLY_REPLY = "当前微信通道首版仅支持文本消息。"
_PROACTIVE_SEND_UNSUPPORTED = (
    "个人微信 iLink 当前仅支持基于活跃会话上下文回复，暂不支持独立主动推送。"
)
_EMPTY_MESSAGE_REPLY = "当前微信通道暂时无法处理空消息。"
_DEFAULT_POLL_TIMEOUT_MS = 35_000


class WeChatAdapter:
    """Long-poll iLink events and route text chats into the unified pipeline."""

    def __init__(
        self,
        config: WeChatConfig,
        msg_hub: MsgHub,
        *,
        state_store: WeChatStateStore | None = None,
        api_client: WeChatIlinkClient | None = None,
    ) -> None:
        self.config = config
        self.msg_hub = msg_hub
        self._store = state_store or WeChatStateStore(config.state_path)
        self._api = api_client or WeChatIlinkClient(config.api_base_url)
        self._state: WeChatLoginState | None = None
        self._poll_task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()
        self._context_tokens: dict[str, str] = {}
        self._status = "starting"
        self._last_error = ""

    @property
    def runtime_status(self) -> str:
        if self._status == "degraded":
            return "degraded"
        if self._poll_task is None:
            return "starting"
        return "ready"

    async def start(self) -> None:
        state = self._store.load()
        if state is None:
            raise RuntimeError("WeChat login state is missing or incomplete.")
        self._state = state
        self._stop_event.clear()
        await self._api.start()
        self._poll_task = asyncio.create_task(
            self._poll_loop(),
            name="wechat-ilink-poll",
        )
        self._status = "ready"
        logger.info("wechat.started", account_id=state.account_id)

    async def stop(self) -> None:
        self._stop_event.set()
        if self._poll_task is not None:
            self._poll_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._poll_task
            self._poll_task = None
        await self._api.stop()
        logger.info("wechat.stopped")

    async def send_message(self, chat_id: str, content: MessageContent) -> None:
        state = self._require_state()
        if not content.text:
            return
        account_id, peer_id = self._parse_conversation_id(chat_id)
        if account_id != state.account_id:
            raise RuntimeError(
                "WeChat conversation account mismatch: "
                f"expected {state.account_id}, got {account_id}"
            )
        context_token = self._context_tokens.get(chat_id)
        if not context_token:
            logger.warning("wechat.proactive_send_unsupported", conversation_id=chat_id)
            raise RuntimeError(_PROACTIVE_SEND_UNSUPPORTED)
        try:
            await self._api.send_text_message(
                bot_token=state.bot_token,
                to_user_id=peer_id,
                text=content.text,
                context_token=context_token,
                base_url=state.api_base_url,
            )
        except ILinkApiError as exc:
            if self._is_context_invalid_error(exc):
                self._context_tokens.pop(chat_id, None)
            raise

    async def _poll_loop(self) -> None:
        delay_seconds = self.config.poll_interval
        timeout_ms = _DEFAULT_POLL_TIMEOUT_MS
        while not self._stop_event.is_set():
            try:
                state = self._require_state()
                response = await self._api.get_updates(
                    bot_token=state.bot_token,
                    get_updates_buf=state.get_updates_buf,
                    base_url=state.api_base_url,
                    timeout_ms=timeout_ms,
                )
                next_timeout = response.get("longpolling_timeout_ms")
                if isinstance(next_timeout, int) and next_timeout > 0:
                    timeout_ms = next_timeout
                cursor = str(response.get("get_updates_buf", ""))
                if cursor and cursor != state.get_updates_buf:
                    state = self._store.update_get_updates_buf(cursor) or state
                    self._state = state
                for message in response.get("msgs", []) or []:
                    if isinstance(message, dict):
                        await self._handle_inbound_message(message)
                self._status = "ready"
                self._last_error = ""
                delay_seconds = self.config.poll_interval
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._status = "degraded"
                self._last_error = str(exc)
                logger.warning("wechat.poll_failed", error=self._last_error)
                await asyncio.sleep(delay_seconds)
                delay_seconds = min(delay_seconds * 2, self.config.max_backoff)

    async def _handle_inbound_message(self, payload: dict[str, Any]) -> None:
        state = self._require_state()
        if str(payload.get("message_type", "")) == "2":
            return
        peer_id = str(payload.get("from_user_id", "")).strip()
        if not peer_id:
            return
        conversation_id = self._conversation_id(state.account_id, peer_id)
        context_token = str(payload.get("context_token", "")).strip()
        if context_token:
            self._context_tokens[conversation_id] = context_token
        if payload.get("group_id"):
            logger.debug("wechat.group_ignored", conversation_id=conversation_id)
            return
        text = self._extract_text(payload.get("item_list"))
        if text is None:
            await self._reply_with_context(conversation_id, peer_id, _TEXT_ONLY_REPLY)
            return
        if not text:
            await self._reply_with_context(conversation_id, peer_id, _EMPTY_MESSAGE_REPLY)
            return
        message = UnifiedMessage(
            id=str(payload.get("message_id") or payload.get("seq") or peer_id),
            platform="wechat",
            sender_id=peer_id,
            conversation_id=conversation_id,
            content=MessageContent(text=text),
        )
        logger.info(
            "wechat.message_received",
            sender_id=peer_id,
            conversation_id=conversation_id,
            text_length=len(text),
        )
        await self.msg_hub.handle_incoming(message)

    async def _reply_with_context(self, conversation_id: str, peer_id: str, text: str) -> None:
        state = self._require_state()
        context_token = self._context_tokens.get(conversation_id)
        if not context_token:
            logger.warning(
                "wechat.context_token_missing",
                conversation_id=conversation_id,
                text=text,
            )
            return
        await self._api.send_text_message(
            bot_token=state.bot_token,
            to_user_id=peer_id,
            text=text,
            context_token=context_token,
            base_url=state.api_base_url,
        )

    def _require_state(self) -> WeChatLoginState:
        if self._state is None:
            raise RuntimeError("WeChat adapter is not logged in.")
        return self._state

    @staticmethod
    def _conversation_id(account_id: str, peer_id: str) -> str:
        return f"wechat:{account_id}:{peer_id}"

    @staticmethod
    def _parse_conversation_id(conversation_id: str) -> tuple[str, str]:
        parts = conversation_id.split(":", 2)
        if len(parts) != 3 or parts[0] != "wechat":
            raise RuntimeError(
                "WeChat target_id must be a conversation id like "
                f"'wechat:<account>:<peer>', got: {conversation_id}"
            )
        return parts[1], parts[2]

    @staticmethod
    def _extract_text(item_list: Any) -> str | None:
        if not isinstance(item_list, list) or not item_list:
            return ""
        for item in item_list:
            if not isinstance(item, dict):
                continue
            if item.get("type") == 1:
                text_item = item.get("text_item") or {}
                text = text_item.get("text")
                return str(text).strip() if text is not None else ""
        return None

    @staticmethod
    def _is_context_invalid_error(exc: ILinkApiError) -> bool:
        errmsg = (exc.errmsg or "").lower()
        return "context" in errmsg and ("invalid" in errmsg or "expired" in errmsg)
