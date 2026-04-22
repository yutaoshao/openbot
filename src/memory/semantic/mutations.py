"""Mutation/storage mixin for semantic memory."""

from __future__ import annotations

import json
import uuid

from src.core.logging import get_logger

from .helpers import (
    VALID_CATEGORIES,
    VALID_PRIORITIES,
    calculate_expires_at,
    normalize_embedding,
)

logger = get_logger(__name__)


class SemanticMutationMixin:
    """Write/update helpers shared by the semantic memory service."""

    async def add_knowledge(
        self,
        user_id: str,
        category: str,
        content: str,
        tags: list[str] | None = None,
        priority: str = "P1",
    ) -> dict:
        if category not in VALID_CATEGORIES:
            category = "fact"
        if priority not in VALID_PRIORITIES:
            priority = "P1"
        embedding = await self._embedding.embed(content)
        entry = await self._create_entry(
            category=category,
            content=content,
            tags=tags or [],
            priority=priority,
            embedding=embedding,
            user_id=user_id,
        )
        logger.info(
            "semantic.add_knowledge",
            knowledge_id=entry["id"],
            category=category,
            priority=priority,
        )
        return entry

    async def cleanup_expired(self) -> int:
        deleted = await self._storage.knowledge.delete_expired()
        orphaned = await self._delete_orphaned_embeddings()
        total = deleted + orphaned
        if total:
            logger.info(
                "semantic.cleanup_expired",
                knowledge_deleted=deleted,
                embeddings_orphaned=orphaned,
            )
        return total

    async def _store_embedding(self, knowledge_id: str, embedding: list[float]) -> None:
        normalized_embedding = normalize_embedding(embedding)
        if not normalized_embedding:
            return
        try:
            async with self._db.get_connection() as conn:
                await conn.execute(
                    """
                    INSERT INTO knowledge_embeddings
                        (knowledge_id, embedding)
                    VALUES (?, ?)
                    """,
                    (knowledge_id, json.dumps(normalized_embedding)),
                )
                await conn.commit()
        except Exception:
            logger.warning(
                "semantic.store_embedding_failed",
                knowledge_id=knowledge_id,
                exc_info=True,
            )

    async def _update_embedding(self, knowledge_id: str, embedding: list[float]) -> None:
        normalized_embedding = normalize_embedding(embedding)
        if not normalized_embedding:
            return
        try:
            async with self._db.get_connection() as conn:
                await conn.execute(
                    "DELETE FROM knowledge_embeddings WHERE knowledge_id = ?",
                    (knowledge_id,),
                )
                await conn.execute(
                    """
                    INSERT INTO knowledge_embeddings
                        (knowledge_id, embedding)
                    VALUES (?, ?)
                    """,
                    (knowledge_id, json.dumps(normalized_embedding)),
                )
                await conn.commit()
        except Exception:
            logger.warning(
                "semantic.update_embedding_failed",
                knowledge_id=knowledge_id,
                exc_info=True,
            )

    async def _delete_orphaned_embeddings(self) -> int:
        try:
            async with self._db.get_connection() as conn:
                cursor = await conn.execute(
                    """
                    DELETE FROM knowledge_embeddings
                    WHERE knowledge_id NOT IN (
                        SELECT id FROM knowledge
                    )
                    """,
                )
                await conn.commit()
                return cursor.rowcount
        except Exception:
            logger.warning("semantic.delete_orphaned_failed", exc_info=True)
            return 0

    async def _create_entry(
        self,
        *,
        category: str,
        content: str,
        tags: list[str],
        priority: str,
        embedding: list[float],
        user_id: str,
        source_conversation_id: str | None = None,
    ) -> dict:
        knowledge_id = uuid.uuid4().hex
        expires_at = calculate_expires_at(priority)

        await self._storage.knowledge.add(
            id=knowledge_id,
            user_id=user_id,
            category=category,
            content=content,
            tags=tags,
            priority=priority,
            confidence=1.0,
            source_conversation_id=source_conversation_id,
            expires_at=expires_at,
        )
        await self._store_embedding(knowledge_id, embedding)
        return {
            "id": knowledge_id,
            "user_id": user_id,
            "category": category,
            "content": content,
            "tags": tags,
            "priority": priority,
            "expires_at": expires_at,
            "source_conversation_id": source_conversation_id,
            "created": True,
        }

    async def _merge_knowledge(
        self,
        existing: dict[str, object],
        new_content: str,
        new_tags: list[str],
        new_priority: str,
    ) -> dict:
        knowledge_id = str(existing["id"])
        priority_order = ["P0", "P1", "P2"]
        old_idx = priority_order.index(str(existing.get("priority", "P1")))
        new_idx = priority_order.index(new_priority)
        merged_priority = priority_order[min(old_idx, new_idx)]
        old_tags: list[str] = existing.get("tags") or []  # type: ignore[assignment]
        merged_tags = list(dict.fromkeys(old_tags + new_tags))
        old_content = str(existing.get("content", ""))
        merged_content = (
            f"{old_content}\n---\n{new_content}"
            if new_content.strip() != old_content.strip()
            else old_content
        )
        expires_at = calculate_expires_at(merged_priority)
        await self._storage.knowledge.update(
            knowledge_id,
            content=merged_content,
            tags=merged_tags,
            priority=merged_priority,
            expires_at=expires_at,
        )
        embedding = await self._embedding.embed(merged_content)
        await self._update_embedding(knowledge_id, embedding)
        logger.debug(
            "semantic.merged_knowledge",
            knowledge_id=knowledge_id,
            priority=merged_priority,
        )
        return {
            "id": knowledge_id,
            "user_id": existing.get("user_id", ""),
            "category": existing.get("category", "fact"),
            "content": merged_content,
            "tags": merged_tags,
            "priority": merged_priority,
            "expires_at": expires_at,
            "merged": True,
        }
