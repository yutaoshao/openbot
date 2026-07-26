"""Working memory for a single conversation.

Manages the message context window with token-budget enforcement and
LLM-driven compression.  Inspired by OpenClaw's pre-compression flush
pattern: before discarding older messages we extract key facts and
decisions so they can be persisted to semantic memory by the caller.
"""

from __future__ import annotations

from collections import OrderedDict
from typing import TYPE_CHECKING, Any

from src.core.logging import get_logger
from src.memory.history_references import history_file_references
from src.memory.message_format import render_llm_message
from src.memory.turn_selection import select_long_term_memory_prefix
from src.memory.working_compaction import extract_memory_items, summarize_messages

if TYPE_CHECKING:
    from src.infrastructure.model_gateway import ModelGateway

logger = get_logger(__name__)

CHARS_PER_TOKEN = 4


class WorkingMemory:
    """Manages the message context window for a single conversation."""

    def __init__(
        self,
        conversation_id: str,
        token_budget: int = 8000,
    ) -> None:
        self._conversation_id = conversation_id
        self._token_budget = token_budget
        self._messages: list[dict[str, Any]] = []  # role/content dicts
        self._pinned: list[dict[str, Any]] = []  # never compressed
        self._protected: OrderedDict[str, str] = OrderedDict()
        self._summary: str | None = None  # compressed summary

    def add(self, message: dict[str, Any]) -> None:
        """Add a message (role, content) to working memory."""
        _validate_message_timestamp(message)
        self._messages.append(message)
        logger.debug(
            "working_memory.add",
            conversation_id=self._conversation_id,
            role=message.get("role"),
            tokens_est=self.estimate_tokens(),
        )

    def pin(self, message: dict[str, Any]) -> None:
        """Add a pinned message that survives compression."""
        self._pinned.append(message)
        logger.debug(
            "working_memory.pin",
            conversation_id=self._conversation_id,
            role=message.get("role"),
        )

    def set_protected(self, key: str, content: str) -> None:
        """Store protected context that must survive compression."""
        if not key:
            return
        cleaned = content.strip()
        if not cleaned:
            self._protected.pop(key, None)
            return
        self._protected[key] = cleaned
        self._protected.move_to_end(key)
        logger.debug(
            "working_memory.protected_set",
            conversation_id=self._conversation_id,
            key=key,
            chars=len(cleaned),
        )

    def get_messages(self) -> list[dict[str, Any]]:
        """Return assembled context: pinned + summary + recent messages."""
        result: list[dict[str, Any]] = []

        result.extend(self._pinned)
        for key, content in self._protected.items():
            result.append(
                {
                    "role": "system",
                    "content": f"Protected Context ({key}):\n{content}",
                }
            )

        if self._summary is not None:
            result.append(
                {
                    "role": "system",
                    "content": (f"Summary of earlier conversation:\n{self._summary}"),
                }
            )

        result.extend(render_llm_message(message) for message in self._messages)
        return result

    def estimate_tokens(self) -> int:
        """Estimate total tokens across all segments (~4 chars/token)."""
        total_chars = 0
        for msg in self._pinned:
            total_chars += len(msg.get("content", ""))
        for content in self._protected.values():
            total_chars += len(content)
        if self._summary is not None:
            total_chars += len(self._summary)
        for msg in self._messages:
            total_chars += len(str(render_llm_message(msg).get("content", "")))
        return total_chars // CHARS_PER_TOKEN

    def needs_compression(self) -> bool:
        """True if estimated tokens exceed the budget."""
        return self.estimate_tokens() > self._token_budget

    def _compression_segments(
        self,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]] | None:
        midpoint = len(self._messages) // 2
        memory_prefix = select_long_term_memory_prefix(self._messages, midpoint)
        if memory_prefix.next_cursor == 0:
            logger.info(
                "working_memory.compress.skip",
                conversation_id=self._conversation_id,
                reason="no_closed_turn",
            )
            return None
        return (
            list(memory_prefix.messages),
            self._messages[memory_prefix.next_cursor :],
        )

    async def compress(self, model_gateway: ModelGateway) -> str:
        """Compress older messages via LLM summarisation.

        Splits ``_messages`` in half, sends the older half to the LLM for
        summarisation, then replaces those messages with the resulting
        summary.  Returns the summary text.
        """
        if len(self._messages) < 2:
            logger.info(
                "working_memory.compress.skip",
                conversation_id=self._conversation_id,
                reason="too_few_messages",
            )
            return self._summary or ""

        segments = self._compression_segments()
        if segments is None:
            return self._summary or ""
        older, recent = segments
        if not older:
            self._messages = recent
            logger.info(
                "working_memory.compress.skip_summary",
                conversation_id=self._conversation_id,
                reason="no_eligible_messages",
            )
            return self._summary or ""
        logger.info(
            "working_memory.compress.start",
            conversation_id=self._conversation_id,
            older_count=len(older),
            recent_count=len(recent),
        )
        summary = await summarize_messages(
            model_gateway=model_gateway,
            messages=older,
        )
        new_summary = _summary_with_history_references(summary, older)
        if self._summary:
            new_summary = f"{self._summary}\n\n{new_summary}"
        self._summary = new_summary
        self._messages = recent
        logger.info(
            "working_memory.compress.done",
            conversation_id=self._conversation_id,
            summary_len=len(new_summary),
            tokens_est=self.estimate_tokens(),
        )
        return new_summary

    async def extract_before_compression(
        self,
        model_gateway: ModelGateway,
    ) -> list[dict[str, str]]:
        """Pre-compression flush: extract key knowledge from older messages.

        Calls the LLM to identify facts, concepts, and procedures from
        the messages that are about to be compressed out.  The caller is
        responsible for persisting the returned items to semantic memory.
        """
        if len(self._messages) < 2:
            return []

        midpoint = len(self._messages) // 2
        memory_prefix = select_long_term_memory_prefix(self._messages, midpoint)
        older = list(memory_prefix.messages)
        if not older:
            return []
        return await extract_memory_items(
            model_gateway=model_gateway,
            messages=older,
            conversation_id=self._conversation_id,
        )


def _validate_message_timestamp(message: dict[str, Any]) -> None:
    if message.get("role") in {"user", "assistant"}:
        render_llm_message(message)


def _summary_with_history_references(summary: str, messages: list[dict[str, Any]]) -> str:
    references = history_file_references(messages)
    return f"{summary}\n\n" + "\n".join(references) if references else summary
