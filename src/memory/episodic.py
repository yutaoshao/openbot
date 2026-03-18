"""Episodic memory -- conversation archival, summary generation, and recall.

Archives completed conversations by generating LLM-powered summaries and
titles, stores summary embeddings in sqlite-vec for semantic recall, and
provides both vector-based and text-based search for past conversations.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from src.platform.logging import get_logger

if TYPE_CHECKING:
    from src.infrastructure.database import Database
    from src.infrastructure.embedding import EmbeddingService
    from src.infrastructure.model_gateway import ModelGateway
    from src.infrastructure.reranker import NullRerankerService, RerankerService
    from src.infrastructure.storage import Storage

logger = get_logger(__name__)

# Number of leading messages fed into the title-generation prompt.
_TITLE_CONTEXT_MESSAGES = 6

# Maximum messages passed into the summary-generation prompt.  Long
# conversations are truncated to the first and last portions.
_SUMMARY_HEAD = 10
_SUMMARY_TAIL = 20

_TITLE_SYSTEM_PROMPT = (
    "You are a concise title generator. "
    "Given the opening messages of a conversation, produce a short title "
    "(less than 50 characters) that captures the main topic. "
    "Return ONLY the title text, with no quotes or extra punctuation."
)

_SUMMARY_SYSTEM_PROMPT = (
    "You are a conversation summarizer. "
    "Given a conversation between a user and an assistant, write a 2-3 "
    "sentence summary covering the key topics discussed, decisions made, "
    "and outcomes reached. "
    "Return ONLY the summary text."
)


def _format_messages_for_llm(
    messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Convert stored message dicts into the {role, content} format the
    model gateway expects, filtering out empty content."""
    formatted: list[dict[str, Any]] = []
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if not content:
            continue
        formatted.append({"role": role, "content": content})
    return formatted


def _truncate_for_summary(
    messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Keep the first *_SUMMARY_HEAD* and last *_SUMMARY_TAIL* messages
    when a conversation is too long, inserting a placeholder in between."""
    total = _SUMMARY_HEAD + _SUMMARY_TAIL
    if len(messages) <= total:
        return messages
    head = messages[:_SUMMARY_HEAD]
    tail = messages[-_SUMMARY_TAIL:]
    omitted = len(messages) - total
    placeholder = {
        "role": "system",
        "content": f"[... {omitted} messages omitted ...]",
    }
    return [*head, placeholder, *tail]


class EpisodicMemory:
    """Manages conversation archival with LLM-generated summaries and
    vector-based semantic recall."""

    def __init__(
        self,
        storage: Storage,
        model_gateway: ModelGateway,
        embedding_service: EmbeddingService,
        db: Database,
        reranker: RerankerService | NullRerankerService | None = None,
    ) -> None:
        self._storage = storage
        self._gateway = model_gateway
        self._embedding = embedding_service
        self._db = db
        self._reranker = reranker

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def on_conversation_end(
        self, conversation_id: str,
    ) -> None:
        """Archive a completed conversation.

        Fetches all messages, generates a title and summary via the LLM,
        persists them on the conversation record, and stores a summary
        embedding for later semantic recall.
        """
        messages = await self._storage.messages.get_by_conversation(
            conversation_id,
        )
        if not messages:
            logger.warning(
                "episodic.archive_skipped",
                conversation_id=conversation_id,
                reason="no_messages",
            )
            return

        llm_messages = _format_messages_for_llm(messages)
        if not llm_messages:
            logger.warning(
                "episodic.archive_skipped",
                conversation_id=conversation_id,
                reason="no_content",
            )
            return

        title, summary = await self._generate_title_and_summary(
            llm_messages,
        )

        await self._storage.conversations.update(
            conversation_id,
            title=title,
            summary=summary,
        )

        await self._store_embedding(conversation_id, summary)

        logger.info(
            "episodic.archived",
            conversation_id=conversation_id,
            title=title,
            summary_len=len(summary),
        )

    async def recall(
        self,
        query: str,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """Recall past conversations relevant to *query*.

        Pipeline: embed → vector search (over-fetch) → rerank (top limit).
        Falls back to text LIKE search when embeddings are unavailable.
        """
        embedding = await self._embedding.embed(query)

        if embedding:
            fetch_n = limit * 3 if self._reranker else limit
            items = await self._recall_by_vector(embedding, fetch_n)
        else:
            logger.debug(
                "episodic.recall_fallback_text",
                reason="embedding_unavailable",
            )
            fetch_n = limit * 3 if self._reranker else limit
            items = await self._storage.conversations.search(
                query, fetch_n,
            )

        # Rerank if available
        if self._reranker and items:
            items = await self._reranker.rerank_dicts(
                query, items, content_key="summary", top_n=limit,
            )
        else:
            items = items[:limit]

        return items

    async def generate_title(
        self, messages: list[dict[str, Any]],
    ) -> str:
        """Generate a concise title (< 50 chars) from the opening
        messages of a conversation."""
        context = messages[:_TITLE_CONTEXT_MESSAGES]
        llm_messages: list[dict[str, Any]] = [
            {"role": "system", "content": _TITLE_SYSTEM_PROMPT},
            *context,
        ]
        try:
            response = await self._gateway.chat(llm_messages)
            title = response.text.strip().strip('"\'')
            return title[:50] if title else "Untitled conversation"
        except Exception:
            logger.warning(
                "episodic.title_generation_failed",
                exc_info=True,
            )
            return "Untitled conversation"

    async def generate_summary(
        self, messages: list[dict[str, Any]],
    ) -> str:
        """Generate a 2-3 sentence summary of a conversation."""
        truncated = _truncate_for_summary(messages)
        llm_messages: list[dict[str, Any]] = [
            {"role": "system", "content": _SUMMARY_SYSTEM_PROMPT},
            *truncated,
        ]
        try:
            response = await self._gateway.chat(llm_messages)
            summary = response.text.strip()
            return summary or "No summary available."
        except Exception:
            logger.warning(
                "episodic.summary_generation_failed",
                exc_info=True,
            )
            return "No summary available."

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _generate_title_and_summary(
        self, llm_messages: list[dict[str, Any]],
    ) -> tuple[str, str]:
        """Run title and summary generation (sequentially to stay within
        rate-limits on smaller deployments)."""
        title = await self.generate_title(llm_messages)
        summary = await self.generate_summary(llm_messages)
        return title, summary

    async def _store_embedding(
        self,
        conversation_id: str,
        summary: str,
    ) -> None:
        """Embed the summary and upsert into the vec0 table."""
        embedding = await self._embedding.embed(summary)
        if not embedding:
            logger.debug(
                "episodic.embedding_skipped",
                conversation_id=conversation_id,
                reason="empty_embedding",
            )
            return

        embedding_json = json.dumps(embedding)
        try:
            async with self._db.get_connection() as conn:
                # Upsert: delete then insert (vec0 does not support
                # ON CONFLICT).
                await conn.execute(
                    "DELETE FROM conversation_embeddings "
                    "WHERE conversation_id = ?",
                    (conversation_id,),
                )
                await conn.execute(
                    "INSERT INTO conversation_embeddings "
                    "(conversation_id, embedding) VALUES (?, ?)",
                    (conversation_id, embedding_json),
                )
                await conn.commit()
            logger.debug(
                "episodic.embedding_stored",
                conversation_id=conversation_id,
                dimensions=len(embedding),
            )
        except Exception:
            logger.warning(
                "episodic.embedding_store_failed",
                conversation_id=conversation_id,
                exc_info=True,
            )

    async def _recall_by_vector(
        self,
        query_embedding: list[float],
        limit: int,
    ) -> list[dict[str, Any]]:
        """Search conversation_embeddings via cosine similarity and
        hydrate matching conversation records."""
        embedding_json = json.dumps(query_embedding)
        try:
            async with self._db.get_connection() as conn:
                cursor = await conn.execute(
                    "SELECT conversation_id, distance "
                    "FROM conversation_embeddings "
                    "WHERE embedding MATCH ? "
                    "ORDER BY distance "
                    "LIMIT ?",
                    (embedding_json, limit),
                )
                rows = await cursor.fetchall()
        except Exception:
            logger.warning(
                "episodic.vector_search_failed",
                exc_info=True,
            )
            return []

        results: list[dict[str, Any]] = []
        for row in rows:
            conv_id = row[0]
            distance = row[1]
            conv = await self._storage.conversations.get(conv_id)
            if conv is not None:
                conv["distance"] = distance
                results.append(conv)
        return results
