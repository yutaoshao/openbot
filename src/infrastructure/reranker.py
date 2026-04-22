"""Reranker service for improving retrieval quality.

Uses the /v1/rerank endpoint (SiliconFlow, Jina, Cohere compatible)
to re-score candidate documents against a query with a cross-encoder
model, producing more accurate relevance rankings than embedding-based
similarity alone.

Pipeline: embed query → vector search (top-N) → rerank (top-K)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import httpx

from src.core.logging import get_logger

if TYPE_CHECKING:
    from src.core.config import RerankerConfig

logger = get_logger(__name__)


@dataclass
class RerankResult:
    """A single reranked item with its original index and relevance score."""

    index: int
    relevance_score: float


class RerankerService:
    """Cross-encoder reranker via /v1/rerank API.

    Supports SiliconFlow, Jina, Cohere, and any provider implementing
    the same endpoint specification.
    """

    def __init__(self, config: RerankerConfig) -> None:
        self.config = config
        self._endpoint = f"{config.base_url.rstrip('/')}/rerank"

        logger.info(
            "reranker_service.init",
            model=config.model,
            base_url=config.base_url,
            top_n=config.top_n,
        )

    async def rerank(
        self,
        query: str,
        documents: list[str],
        top_n: int | None = None,
    ) -> list[RerankResult]:
        """Rerank documents against a query.

        Args:
            query: The search query.
            documents: List of candidate document texts.
            top_n: Override default top_n from config.

        Returns:
            Sorted list of RerankResult (highest relevance first).
            Returns empty list on error.
        """
        if not documents:
            return []

        effective_top_n = top_n or self.config.top_n

        payload: dict[str, Any] = {
            "model": self.config.model,
            "query": query,
            "documents": documents,
            "top_n": min(effective_top_n, len(documents)),
            "return_documents": False,
        }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    self._endpoint,
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {self.config.api_key}",
                        "Content-Type": "application/json",
                    },
                )
                response.raise_for_status()
                data = response.json()

            results = [
                RerankResult(
                    index=item["index"],
                    relevance_score=item["relevance_score"],
                )
                for item in data.get("results", [])
            ]

            # Sort by relevance score descending
            results.sort(key=lambda r: r.relevance_score, reverse=True)

            logger.debug(
                "reranker.success",
                query_len=len(query),
                candidates=len(documents),
                returned=len(results),
                top_score=results[0].relevance_score if results else 0,
            )
            return results

        except httpx.HTTPStatusError as e:
            logger.warning(
                "reranker.http_error",
                status=e.response.status_code,
                body=e.response.text[:200],
            )
            return []
        except Exception:
            logger.warning("reranker.failed", exc_info=True)
            return []

    async def rerank_dicts(
        self,
        query: str,
        items: list[dict[str, Any]],
        content_key: str = "content",
        top_n: int | None = None,
    ) -> list[dict[str, Any]]:
        """Rerank a list of dicts by their content field.

        Convenience method for memory recall results. Extracts text from
        each dict via *content_key*, reranks, and returns the reordered
        dicts with an added ``_rerank_score`` field.

        Args:
            query: The search query.
            items: List of dicts (e.g. knowledge entries).
            content_key: Dict key containing the text to rerank.
            top_n: Override default top_n from config.

        Returns:
            Reordered list of dicts, highest relevance first.
            Falls back to original order on error.
        """
        if not items:
            return []

        documents = [str(item.get(content_key, ""))[:2000] for item in items]

        results = await self.rerank(query, documents, top_n)

        if not results:
            # Fallback: return original items unchanged
            return items

        reranked: list[dict[str, Any]] = []
        for r in results:
            if 0 <= r.index < len(items):
                item = items[r.index].copy()
                item["_rerank_score"] = r.relevance_score
                reranked.append(item)

        return reranked


class NullRerankerService:
    """No-op reranker for when reranking is not configured."""

    async def rerank(
        self,
        query: str,  # noqa: ARG002
        documents: list[str],  # noqa: ARG002
        top_n: int | None = None,  # noqa: ARG002
    ) -> list[RerankResult]:
        """Always returns empty list (passthrough)."""
        return []

    async def rerank_dicts(
        self,
        query: str,  # noqa: ARG002
        items: list[dict[str, Any]],
        content_key: str = "content",  # noqa: ARG002
        top_n: int | None = None,  # noqa: ARG002
    ) -> list[dict[str, Any]]:
        """Returns items unchanged (passthrough)."""
        return items
