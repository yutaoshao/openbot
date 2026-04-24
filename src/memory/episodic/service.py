"""Episodic memory service implementation."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from src.core.logging import get_logger

from .helpers import (
    SUMMARY_SYSTEM_PROMPT,
    TITLE_CONTEXT_MESSAGES,
    TITLE_SYSTEM_PROMPT,
    belongs_to_user,
    format_messages_for_llm,
    normalize_embedding,
    render_transcript,
    sanitize_title,
    truncate_for_summary,
)

if TYPE_CHECKING:
    from src.infrastructure.database import Database
    from src.infrastructure.embedding import EmbeddingService
    from src.infrastructure.model_gateway import ModelGateway
    from src.infrastructure.reranker import NullRerankerService, RerankerService
    from src.infrastructure.storage import Storage

logger = get_logger(__name__)


class EpisodicMemory:
    """Manages conversation archival with semantic recall."""

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

    async def on_conversation_end(self, conversation_id: str, user_id: str) -> None:
        messages = await self._storage.messages.get_by_conversation(conversation_id)
        if not messages:
            logger.warning(
                "episodic.archive_skipped",
                conversation_id=conversation_id,
                reason="no_messages",
            )
            return

        llm_messages = format_messages_for_llm(messages)
        if not llm_messages:
            logger.warning(
                "episodic.archive_skipped",
                conversation_id=conversation_id,
                reason="no_content",
            )
            return

        title, summary = await self._generate_title_and_summary(llm_messages)
        await self._storage.conversations.update(
            conversation_id,
            title=title,
            summary=summary,
        )
        await self._store_embedding(conversation_id, summary)
        logger.info(
            "episodic.archived",
            conversation_id=conversation_id,
            user_id=user_id,
            title=title,
            summary_len=len(summary),
        )

    async def recall(
        self,
        query: str,
        user_id: str,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        embedding = await self._embedding.embed(query)
        if embedding:
            fetch_n = limit * 3 if self._reranker else limit
            items = await self._recall_by_vector(embedding, fetch_n, user_id)
        else:
            fetch_n = limit * 3 if self._reranker else limit
            items = await self._storage.conversations.search(query, fetch_n)
            items = self._filter_conversations(items, user_id)

        if self._reranker and items:
            items = await self._reranker.rerank_dicts(
                query,
                items,
                content_key="summary",
                top_n=limit,
            )
        else:
            items = items[:limit]
        return items

    async def generate_title(self, messages: list[dict[str, Any]]) -> str:
        transcript = render_transcript(messages[:TITLE_CONTEXT_MESSAGES])
        llm_messages = [
            {"role": "system", "content": TITLE_SYSTEM_PROMPT},
            {"role": "user", "content": f"Conversation opening:\n{transcript}"},
        ]
        try:
            response = await self._gateway.chat(llm_messages)
            return sanitize_title(response.text)
        except Exception:
            logger.warning("episodic.title_generation_failed", exc_info=True)
            return "Untitled conversation"

    async def generate_summary(self, messages: list[dict[str, Any]]) -> str:
        transcript = render_transcript(truncate_for_summary(messages))
        llm_messages = [
            {"role": "system", "content": SUMMARY_SYSTEM_PROMPT},
            {"role": "user", "content": f"Conversation transcript:\n{transcript}"},
        ]
        try:
            response = await self._gateway.chat(llm_messages)
            summary = response.text.strip()
            return summary or "No summary available."
        except Exception:
            logger.warning("episodic.summary_generation_failed", exc_info=True)
            return "No summary available."

    async def _generate_title_and_summary(
        self,
        llm_messages: list[dict[str, Any]],
    ) -> tuple[str, str]:
        title = await self.generate_title(llm_messages)
        summary = await self.generate_summary(llm_messages)
        return title, summary

    async def _store_embedding(self, conversation_id: str, summary: str) -> None:
        embedding = await self._embedding.embed(summary)
        normalized_embedding = normalize_embedding(embedding)
        if not normalized_embedding:
            logger.debug(
                "episodic.embedding_skipped",
                conversation_id=conversation_id,
                reason="empty_embedding",
            )
            return
        try:
            async with self._db.get_connection() as conn:
                await conn.execute(
                    "DELETE FROM conversation_embeddings WHERE conversation_id = ?",
                    (conversation_id,),
                )
                await conn.execute(
                    """
                    INSERT INTO conversation_embeddings
                        (conversation_id, embedding)
                    VALUES (?, ?)
                    """,
                    (conversation_id, json.dumps(normalized_embedding)),
                )
                await conn.commit()
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
        user_id: str,
    ) -> list[dict[str, Any]]:
        normalized_query = normalize_embedding(query_embedding)
        if not normalized_query:
            return []
        try:
            async with self._db.get_connection() as conn:
                cursor = await conn.execute(
                    """
                    SELECT conversation_id, distance
                    FROM conversation_embeddings
                    WHERE embedding MATCH ?
                    ORDER BY distance
                    LIMIT ?
                    """,
                    (json.dumps(normalized_query), limit),
                )
                rows = await cursor.fetchall()
        except Exception:
            logger.warning("episodic.vector_search_failed", exc_info=True)
            return []

        results: list[dict[str, Any]] = []
        for conversation_id, distance in rows:
            conversation = await self._storage.conversations.get(conversation_id)
            if conversation is not None and belongs_to_user(conversation, user_id):
                conversation["distance"] = distance
                results.append(conversation)
        return results

    @staticmethod
    def _filter_conversations(
        items: list[dict[str, Any]],
        user_id: str,
    ) -> list[dict[str, Any]]:
        return [item for item in items if belongs_to_user(item, user_id)]
