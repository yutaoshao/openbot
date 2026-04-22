"""Query/extraction mixin for semantic memory."""

from __future__ import annotations

import json
from typing import Any

from src.core.logging import get_logger

from .helpers import (
    DUPLICATE_THRESHOLD,
    EXTRACTION_PROMPT,
    belongs_to_user,
    format_messages,
    l2_distance_to_cosine_similarity,
    normalize_embedding,
    parse_extraction_response,
)

logger = get_logger(__name__)


class SemanticQueryMixin:
    """Read/query helpers shared by the semantic memory service."""

    async def recall(
        self,
        query: str,
        user_id: str,
        limit: int = 5,
    ) -> list[dict]:
        embedding = await self._embedding.embed(query)
        if embedding:
            fetch_n = limit * 3 if self._reranker else limit
            items = await self._vector_search(embedding, fetch_n, user_id)
        else:
            items = await self._storage.knowledge.search(
                query,
                limit=limit * 3 if self._reranker else limit,
                user_id=user_id,
                include_legacy=True,
            )

        if self._reranker and items:
            items = await self._reranker.rerank_dicts(
                query,
                items,
                content_key="content",
                top_n=limit,
            )
        else:
            items = items[:limit]

        for item in items:
            try:
                await self._storage.knowledge.increment_access(item["id"])
            except Exception:
                logger.warning(
                    "semantic.increment_access_failed",
                    knowledge_id=item.get("id"),
                    exc_info=True,
                )
        logger.debug(
            "semantic.recall",
            query_len=len(query),
            results=len(items),
            used_vectors=bool(embedding),
            used_reranker=bool(self._reranker and items),
        )
        return items

    async def _call_extraction_llm(self, messages: list[dict]) -> list[dict[str, Any]]:
        prompt = EXTRACTION_PROMPT + format_messages(messages)
        try:
            response = await self._gateway.chat([{"role": "user", "content": prompt}])
        except Exception:
            logger.error("semantic.extraction_llm_failed", exc_info=True)
            return []
        return parse_extraction_response(response.text)

    async def _find_duplicate(
        self,
        embedding: list[float],
        content: str,
        user_id: str = "",
    ) -> dict[str, Any] | None:
        normalized_embedding = normalize_embedding(embedding)
        if not normalized_embedding:
            return None

        try:
            async with self._db.get_connection() as conn:
                cursor = await conn.execute(
                    """
                    SELECT knowledge_id, distance
                    FROM knowledge_embeddings
                    WHERE embedding MATCH ?
                    ORDER BY distance
                    LIMIT 1
                    """,
                    (json.dumps(normalized_embedding),),
                )
                row = await cursor.fetchone()
        except Exception:
            logger.warning("semantic.duplicate_search_failed", exc_info=True)
            return None

        if row is None:
            return None

        similarity = l2_distance_to_cosine_similarity(row[1])
        if similarity < DUPLICATE_THRESHOLD:
            return None

        existing = await self._storage.knowledge.get(row[0])
        if existing is None or existing.get("user_id", "") != user_id:
            return None

        logger.debug(
            "semantic.duplicate_found",
            existing_id=row[0],
            similarity=round(similarity, 3),
            content_preview=content[:60],
        )
        return existing

    async def _vector_search(
        self,
        embedding: list[float],
        limit: int,
        user_id: str = "",
    ) -> list[dict[str, Any]]:
        normalized_embedding = normalize_embedding(embedding)
        if not normalized_embedding:
            return []
        try:
            async with self._db.get_connection() as conn:
                cursor = await conn.execute(
                    """
                    SELECT knowledge_id, distance
                    FROM knowledge_embeddings
                    WHERE embedding MATCH ?
                    ORDER BY distance
                    LIMIT ?
                    """,
                    (json.dumps(normalized_embedding), limit),
                )
                rows = await cursor.fetchall()
        except Exception:
            logger.warning("semantic.vector_search_failed", exc_info=True)
            return []

        results: list[dict[str, Any]] = []
        for knowledge_id, distance in rows:
            entry = await self._storage.knowledge.get(knowledge_id)
            if entry is not None and belongs_to_user(entry, user_id):
                entry["_distance"] = distance
                results.append(entry)
        return results
