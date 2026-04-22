"""Semantic memory service implementation."""

from __future__ import annotations

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
            duplicate = await self._find_duplicate(embedding, content, user_id)
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
            )
            results.append(entry)

        logger.info(
            "semantic.extract_knowledge",
            conversation_id=conversation_id,
            extracted=len(raw_items),
            stored=len(results),
        )
        return results
