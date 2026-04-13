"""Working memory for a single conversation.

Manages the message context window with token-budget enforcement and
LLM-driven compression.  Inspired by OpenClaw's pre-compression flush
pattern: before discarding older messages we extract key facts and
decisions so they can be persisted to semantic memory by the caller.
"""

from __future__ import annotations

import json
from collections import OrderedDict
from typing import TYPE_CHECKING, Any

from src.core.logging import get_logger

if TYPE_CHECKING:
    from src.infrastructure.model_gateway import ModelGateway

logger = get_logger(__name__)

CHARS_PER_TOKEN = 4

_COMPRESS_PROMPT = """\
Summarise the following conversation messages concisely.
Preserve:
- Key decisions and action items
- Important facts and conclusions
- Entity names, technical terms, and specific values
- User preferences and constraints

Discard greetings, filler, and redundant exchanges.
Return ONLY the summary text, nothing else.

Messages:
{messages}
"""

_EXTRACT_PROMPT = """\
Analyse the following conversation messages and extract important \
knowledge items that should be remembered long-term.

For each item, classify it into exactly one category:
- fact      : concrete information, data points, stated truths
- concept   : ideas, explanations, mental models
- procedure : how-to steps, workflows, user preferences on process

Filter out noise (greetings, filler, acknowledgements).

Return a JSON array of objects with keys "category" and "content".
Example:
[
  {{"category": "fact", "content": "User's timezone is Asia/Shanghai"}},
  {{"category": "procedure", "content": "Deploy via 'make release' then tag"}}
]

Return ONLY the JSON array, no markdown fences or extra text.
If nothing worth extracting, return an empty array: []

Messages:
{messages}
"""


def _format_messages(messages: list[dict[str, Any]]) -> str:
    """Render a message list into a compact text block for LLM prompts."""
    parts: list[str] = []
    for msg in messages:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        parts.append(f"[{role}] {content}")
    return "\n".join(parts)


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

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def add(self, message: dict[str, Any]) -> None:
        """Add a message (role, content) to working memory."""
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

        result.extend(self._messages)
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
            total_chars += len(msg.get("content", ""))
        return total_chars // CHARS_PER_TOKEN

    def needs_compression(self) -> bool:
        """True if estimated tokens exceed the budget."""
        return self.estimate_tokens() > self._token_budget

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

        midpoint = len(self._messages) // 2
        older = self._messages[:midpoint]
        recent = self._messages[midpoint:]

        prompt = _COMPRESS_PROMPT.format(
            messages=_format_messages(older),
        )

        logger.info(
            "working_memory.compress.start",
            conversation_id=self._conversation_id,
            older_count=len(older),
            recent_count=len(recent),
        )

        response = await model_gateway.chat(
            messages=[{"role": "user", "content": prompt}],
        )

        new_summary = response.text.strip()

        # Merge with any existing summary
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
        older = self._messages[:midpoint]

        prompt = _EXTRACT_PROMPT.format(
            messages=_format_messages(older),
        )

        logger.info(
            "working_memory.extract.start",
            conversation_id=self._conversation_id,
            message_count=len(older),
        )

        response = await model_gateway.chat(
            messages=[{"role": "user", "content": prompt}],
        )

        raw = response.text.strip()

        try:
            items = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning(
                "working_memory.extract.parse_error",
                conversation_id=self._conversation_id,
                raw_length=len(raw),
            )
            return []

        if not isinstance(items, list):
            logger.warning(
                "working_memory.extract.unexpected_type",
                conversation_id=self._conversation_id,
                type=type(items).__name__,
            )
            return []

        valid: list[dict[str, str]] = []
        allowed_categories = {"fact", "concept", "procedure"}
        for item in items:
            if (
                isinstance(item, dict)
                and isinstance(item.get("category"), str)
                and isinstance(item.get("content"), str)
                and item["category"] in allowed_categories
            ):
                valid.append(
                    {
                        "category": item["category"],
                        "content": item["content"],
                    }
                )

        logger.info(
            "working_memory.extract.done",
            conversation_id=self._conversation_id,
            extracted=len(valid),
            discarded=len(items) - len(valid),
        )

        return valid
