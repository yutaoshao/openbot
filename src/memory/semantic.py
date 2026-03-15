"""Semantic memory: knowledge extraction, vector search, and lifecycle.

Extracts persistent knowledge from conversations via LLM, stores it with
embeddings for vector similarity search, and manages priority-based TTL
and deduplication.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from src.platform.logging import get_logger

if TYPE_CHECKING:
    from src.infrastructure.database import Database
    from src.infrastructure.embedding import EmbeddingService
    from src.infrastructure.model_gateway import ModelGateway
    from src.infrastructure.storage import Storage

logger = get_logger(__name__)

# Priority -> TTL mapping
_PRIORITY_TTL: dict[str, timedelta | None] = {
    "P0": None,           # permanent
    "P1": timedelta(days=90),
    "P2": timedelta(days=30),
}

_VALID_CATEGORIES = {"fact", "concept", "procedure", "reference"}
_VALID_PRIORITIES = {"P0", "P1", "P2"}
_DUPLICATE_THRESHOLD = 0.85

_EXTRACTION_PROMPT = """\
You are a knowledge extraction engine. Analyze the conversation below and \
extract persistent, actionable knowledge items.

Rules:
- Extract ONLY facts, concepts, procedures, or references worth remembering.
- Skip greetings, filler, transient context, and small talk.
- Each item must be self-contained and useful without the original conversation.
- Assign a priority:
  P0 = critical/permanent facts (identity, core preferences, key decisions)
  P1 = useful information (technical details, project context, how-tos)
  P2 = minor details (casual mentions, low-impact notes)

Return a JSON array. Each element:
{
  "category": "fact" | "concept" | "procedure" | "reference",
  "content": "<concise knowledge statement>",
  "tags": ["tag1", "tag2"],
  "priority": "P0" | "P1" | "P2"
}

If nothing worth extracting, return an empty array: []

Conversation:
"""


class SemanticMemory:
    """Manages the semantic (knowledge) tier of the memory system."""

    def __init__(
        self,
        storage: Storage,
        model_gateway: ModelGateway,
        embedding_service: EmbeddingService,
        db: Database,
    ) -> None:
        self._storage = storage
        self._gateway = model_gateway
        self._embedding = embedding_service
        self._db = db

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def extract_knowledge(
        self,
        messages: list[dict],
        conversation_id: str,
    ) -> list[dict]:
        """Extract knowledge items from conversation messages via LLM.

        Performs signal/noise filtering, deduplication against existing
        knowledge (vector similarity > 0.85), and priority-based TTL.

        Returns the list of created or updated knowledge dicts.
        """
        if not messages:
            return []

        raw_items = await self._call_extraction_llm(messages)
        if not raw_items:
            return []

        results: list[dict] = []
        for item in raw_items:
            category = item.get("category", "fact")
            content = item.get("content", "")
            tags = item.get("tags") or []
            priority = item.get("priority", "P1")

            if not content:
                continue
            if category not in _VALID_CATEGORIES:
                category = "fact"
            if priority not in _VALID_PRIORITIES:
                priority = "P1"

            # Generate embedding for dedup check
            embedding = await self._embedding.embed(content)

            # Check for duplicates via vector similarity
            duplicate = await self._find_duplicate(embedding, content)
            if duplicate is not None:
                # Merge: update existing entry
                merged = await self._merge_knowledge(
                    duplicate, content, tags, priority,
                )
                results.append(merged)
                continue

            # Create new knowledge entry
            entry = await self._create_entry(
                category=category,
                content=content,
                tags=tags,
                priority=priority,
                embedding=embedding,
                source_conversation_id=conversation_id,
            )
            results.append(entry)

        logger.info(
            "semantic.extract_knowledge",
            conversation_id=conversation_id,
            extracted=len(raw_items),
            stored=len(results),
        )
        return results

    async def recall(
        self,
        query: str,
        limit: int = 5,
    ) -> list[dict]:
        """Retrieve knowledge relevant to *query* via vector similarity.

        Falls back to text LIKE search when embeddings are disabled.
        Increments ``access_count`` for each returned item.
        """
        embedding = await self._embedding.embed(query)

        if embedding:
            items = await self._vector_search(embedding, limit)
        else:
            # Fallback: text search
            items = await self._storage.knowledge.search(query, limit=limit)

        # Bump access counts (fire-and-forget style, errors logged)
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
        )
        return items

    async def add_knowledge(
        self,
        category: str,
        content: str,
        tags: list[str] | None = None,
        priority: str = "P1",
    ) -> dict:
        """Manually add a knowledge entry (for API / frontend use)."""
        if category not in _VALID_CATEGORIES:
            category = "fact"
        if priority not in _VALID_PRIORITIES:
            priority = "P1"

        embedding = await self._embedding.embed(content)
        entry = await self._create_entry(
            category=category,
            content=content,
            tags=tags or [],
            priority=priority,
            embedding=embedding,
        )
        logger.info(
            "semantic.add_knowledge",
            knowledge_id=entry["id"],
            category=category,
            priority=priority,
        )
        return entry

    async def cleanup_expired(self) -> int:
        """Delete expired knowledge and orphaned embeddings.

        Returns the total number of deleted entries.
        """
        deleted = await self._storage.knowledge.delete_expired()

        # Clean up orphaned embeddings (no matching knowledge row)
        orphaned = await self._delete_orphaned_embeddings()

        total = deleted + orphaned
        if total:
            logger.info(
                "semantic.cleanup_expired",
                knowledge_deleted=deleted,
                embeddings_orphaned=orphaned,
            )
        return total

    # ------------------------------------------------------------------
    # TTL calculation
    # ------------------------------------------------------------------

    @staticmethod
    def _calculate_expires_at(priority: str) -> str | None:
        """Return ISO-8601 expiry timestamp based on priority.

        P0 -> None (permanent), P1 -> +90 days, P2 -> +30 days.
        """
        ttl = _PRIORITY_TTL.get(priority)
        if ttl is None:
            return None
        return (datetime.now(UTC) + ttl).isoformat()

    # ------------------------------------------------------------------
    # LLM extraction
    # ------------------------------------------------------------------

    async def _call_extraction_llm(
        self,
        messages: list[dict],
    ) -> list[dict[str, Any]]:
        """Ask the LLM to extract knowledge from conversation messages."""
        conversation_text = self._format_messages(messages)
        prompt = _EXTRACTION_PROMPT + conversation_text

        try:
            response = await self._gateway.chat(
                [{"role": "user", "content": prompt}],
            )
        except Exception:
            logger.error(
                "semantic.extraction_llm_failed", exc_info=True,
            )
            return []

        return self._parse_extraction_response(response.text)

    @staticmethod
    def _format_messages(messages: list[dict]) -> str:
        """Format message dicts into a readable conversation transcript."""
        lines: list[str] = []
        for msg in messages:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            lines.append(f"{role}: {content}")
        return "\n".join(lines)

    @staticmethod
    def _parse_extraction_response(text: str) -> list[dict[str, Any]]:
        """Parse JSON array from LLM response, tolerating markdown fences."""
        cleaned = text.strip()

        # Strip markdown code fences if present
        if cleaned.startswith("```"):
            first_newline = cleaned.find("\n")
            if first_newline != -1:
                cleaned = cleaned[first_newline + 1:]
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3].rstrip()

        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError:
            logger.warning(
                "semantic.parse_extraction_failed",
                response_len=len(text),
            )
            return []

        if not isinstance(parsed, list):
            return []
        return [item for item in parsed if isinstance(item, dict)]

    # ------------------------------------------------------------------
    # Vector operations
    # ------------------------------------------------------------------

    async def _find_duplicate(
        self,
        embedding: list[float],
        content: str,
    ) -> dict[str, Any] | None:
        """Find an existing knowledge entry that is a near-duplicate.

        Uses vector similarity when embeddings are available, otherwise
        skips dedup (returns None).
        """
        if not embedding:
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
                    (json.dumps(embedding),),
                )
                row = await cursor.fetchone()
        except Exception:
            logger.warning(
                "semantic.duplicate_search_failed", exc_info=True,
            )
            return None

        if row is None:
            return None

        knowledge_id = row[0]
        distance = row[1]

        # sqlite-vec returns cosine *distance*; similarity = 1 - distance
        similarity = 1.0 - distance
        if similarity < _DUPLICATE_THRESHOLD:
            return None

        existing = await self._storage.knowledge.get(knowledge_id)
        if existing is None:
            return None

        logger.debug(
            "semantic.duplicate_found",
            existing_id=knowledge_id,
            similarity=round(similarity, 3),
            content_preview=content[:60],
        )
        return existing

    async def _vector_search(
        self,
        embedding: list[float],
        limit: int,
    ) -> list[dict[str, Any]]:
        """Search knowledge_embeddings vec0 table for similar entries."""
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
                    (json.dumps(embedding), limit),
                )
                rows = await cursor.fetchall()
        except Exception:
            logger.warning(
                "semantic.vector_search_failed", exc_info=True,
            )
            return []

        results: list[dict[str, Any]] = []
        for row in rows:
            knowledge_id = row[0]
            entry = await self._storage.knowledge.get(knowledge_id)
            if entry is not None:
                entry["_distance"] = row[1]
                results.append(entry)

        return results

    async def _store_embedding(
        self,
        knowledge_id: str,
        embedding: list[float],
    ) -> None:
        """Insert an embedding vector into the knowledge_embeddings table."""
        if not embedding:
            return
        try:
            async with self._db.get_connection() as conn:
                await conn.execute(
                    """
                    INSERT INTO knowledge_embeddings
                        (knowledge_id, embedding)
                    VALUES (?, ?)
                    """,
                    (knowledge_id, json.dumps(embedding)),
                )
                await conn.commit()
        except Exception:
            logger.warning(
                "semantic.store_embedding_failed",
                knowledge_id=knowledge_id,
                exc_info=True,
            )

    async def _update_embedding(
        self,
        knowledge_id: str,
        embedding: list[float],
    ) -> None:
        """Replace the embedding for an existing knowledge entry."""
        if not embedding:
            return
        try:
            async with self._db.get_connection() as conn:
                # vec0 tables don't support UPDATE; delete + re-insert
                await conn.execute(
                    "DELETE FROM knowledge_embeddings "
                    "WHERE knowledge_id = ?",
                    (knowledge_id,),
                )
                await conn.execute(
                    """
                    INSERT INTO knowledge_embeddings
                        (knowledge_id, embedding)
                    VALUES (?, ?)
                    """,
                    (knowledge_id, json.dumps(embedding)),
                )
                await conn.commit()
        except Exception:
            logger.warning(
                "semantic.update_embedding_failed",
                knowledge_id=knowledge_id,
                exc_info=True,
            )

    async def _delete_orphaned_embeddings(self) -> int:
        """Remove embedding rows whose knowledge entry no longer exists."""
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
            logger.warning(
                "semantic.delete_orphaned_failed", exc_info=True,
            )
            return 0

    # ------------------------------------------------------------------
    # Entry creation / merging
    # ------------------------------------------------------------------

    async def _create_entry(
        self,
        *,
        category: str,
        content: str,
        tags: list[str],
        priority: str,
        embedding: list[float],
        source_conversation_id: str | None = None,
    ) -> dict[str, Any]:
        """Persist a new knowledge entry and its embedding."""
        kid = uuid.uuid4().hex
        expires_at = self._calculate_expires_at(priority)

        await self._storage.knowledge.add(
            id=kid,
            category=category,
            content=content,
            tags=tags,
            priority=priority,
            confidence=1.0,
            source_conversation_id=source_conversation_id,
            expires_at=expires_at,
        )
        await self._store_embedding(kid, embedding)

        return {
            "id": kid,
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
        existing: dict[str, Any],
        new_content: str,
        new_tags: list[str],
        new_priority: str,
    ) -> dict[str, Any]:
        """Merge new knowledge into an existing near-duplicate entry.

        Keeps the higher priority, unions the tags, and appends content
        if it adds meaningful information.
        """
        kid = existing["id"]

        # Determine merged priority (lower ordinal = higher importance)
        priority_order = ["P0", "P1", "P2"]
        old_idx = priority_order.index(existing.get("priority", "P1"))
        new_idx = priority_order.index(new_priority)
        merged_priority = priority_order[min(old_idx, new_idx)]

        # Union tags
        old_tags: list[str] = existing.get("tags") or []
        merged_tags = list(dict.fromkeys(old_tags + new_tags))

        # Append content if substantially different
        old_content: str = existing.get("content", "")
        if new_content.strip() != old_content.strip():
            merged_content = f"{old_content}\n---\n{new_content}"
        else:
            merged_content = old_content

        expires_at = self._calculate_expires_at(merged_priority)

        await self._storage.knowledge.update(
            kid,
            content=merged_content,
            tags=merged_tags,
            priority=merged_priority,
            expires_at=expires_at,
        )

        # Re-embed the merged content
        embedding = await self._embedding.embed(merged_content)
        await self._update_embedding(kid, embedding)

        logger.debug(
            "semantic.merged_knowledge",
            knowledge_id=kid,
            priority=merged_priority,
        )
        return {
            "id": kid,
            "category": existing.get("category", "fact"),
            "content": merged_content,
            "tags": merged_tags,
            "priority": merged_priority,
            "expires_at": expires_at,
            "merged": True,
        }
