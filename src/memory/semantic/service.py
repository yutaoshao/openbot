"""Semantic memory service implementation."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

from src.core.logging import get_logger

from .helpers import VALID_CATEGORIES, VALID_PRIORITIES
from .mutations import SemanticMutationMixin
from .queries import SemanticQueryMixin

if TYPE_CHECKING:
    from src.infrastructure.database import Database
    from src.infrastructure.embedding import EmbeddingService
    from src.infrastructure.model_gateway import ModelGateway
    from src.infrastructure.reranker import NullRerankerService, RerankerService
    from src.infrastructure.storage import Storage

logger = get_logger(__name__)


class SemanticMemory(SemanticMutationMixin, SemanticQueryMixin):
    """Manages the semantic (knowledge) tier of the memory system."""

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

    async def extract_knowledge(
        self,
        messages: list[dict],
        conversation_id: str,
        user_id: str,
    ) -> list[dict]:
        if not messages:
            return []

        raw_items = await self._call_extraction_llm(messages)
        return await self.store_extracted_knowledge(raw_items, conversation_id, user_id)

    async def extract_items(self, messages: list[dict]) -> list[dict]:
        return await self._call_extraction_llm(messages)

    async def store_extracted_knowledge(
        self,
        raw_items: list[dict],
        conversation_id: str,
        user_id: str,
        *,
        source: str | None = None,
    ) -> list[dict]:
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
            if category not in VALID_CATEGORIES:
                category = "fact"
            if priority not in VALID_PRIORITIES:
                priority = "P1"

            embedding = await self._embedding.embed(content)
            knowledge_id = (
                hashlib.sha256(f"{source}\n{content}".encode()).hexdigest() if source else None
            )
            existing = await self._storage.knowledge.get(knowledge_id) if knowledge_id else None
            if existing:
                await self._update_embedding(knowledge_id, embedding)
                results.append(existing)
                continue
            duplicate = (
                await self._find_duplicate(embedding, content, user_id) if source is None else None
            )
            if duplicate is not None:
                merged = await self._merge_knowledge(duplicate, content, tags, priority)
                results.append(merged)
                continue

            entry = await self._create_entry(
                category=category,
                content=content,
                tags=tags,
                priority=priority,
                embedding=embedding,
                user_id=user_id,
                source_conversation_id=conversation_id,
                knowledge_id=knowledge_id,
            )
            results.append(entry)

        logger.info(
            "semantic.extract_knowledge",
            conversation_id=conversation_id,
            extracted=len(raw_items),
            stored=len(results),
        )
        return results
