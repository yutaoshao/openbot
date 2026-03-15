"""Text embedding generation for vector search.

Uses OpenAI-compatible embedding endpoints (DashScope, Volcengine, etc.)
to produce vectors stored in sqlite-vec.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel

from src.platform.logging import get_logger

if TYPE_CHECKING:
    from openai import AsyncOpenAI

logger = get_logger(__name__)


class EmbeddingConfig(BaseModel):
    """Configuration for the embedding service."""

    enabled: bool = False
    provider: Literal["openai_compatible"] = "openai_compatible"
    model: str = "text-embedding-v3"
    base_url: str | None = None
    api_key_env: str = "DASHSCOPE_API_KEY"
    dimensions: int = 1024

    @property
    def api_key(self) -> str:
        """Resolve API key from the environment variable."""
        return os.environ.get(self.api_key_env, "")


class EmbeddingService:
    """Generates text embeddings via an OpenAI-compatible endpoint."""

    def __init__(self, config: EmbeddingConfig) -> None:
        self.config = config
        self._client: AsyncOpenAI | None = None

        if config.enabled:
            self._client = self._create_client()
            logger.info(
                "embedding_service.init",
                model=config.model,
                dimensions=config.dimensions,
                base_url=config.base_url,
            )
        else:
            logger.info("embedding_service.disabled")

    def _create_client(self) -> AsyncOpenAI:
        """Create the underlying OpenAI async client."""
        from openai import AsyncOpenAI

        return AsyncOpenAI(
            api_key=self.config.api_key,
            base_url=self.config.base_url,
        )

    async def embed(self, text: str) -> list[float]:
        """Generate an embedding vector for a single text.

        Returns an empty list when the service is disabled or on error.
        """
        if not self.config.enabled or self._client is None:
            return []

        try:
            response = await self._client.embeddings.create(
                model=self.config.model,
                input=text,
                dimensions=self.config.dimensions,
            )
            return response.data[0].embedding
        except Exception:
            logger.warning(
                "embedding_service.embed_failed",
                model=self.config.model,
                text_len=len(text),
                exc_info=True,
            )
            return []

    async def embed_batch(
        self, texts: list[str],
    ) -> list[list[float]]:
        """Generate embedding vectors for a batch of texts.

        Returns a list of empty lists (one per input text) on failure.
        """
        if not self.config.enabled or self._client is None:
            return [[] for _ in texts]

        if not texts:
            return []

        try:
            response = await self._client.embeddings.create(
                model=self.config.model,
                input=texts,
                dimensions=self.config.dimensions,
            )
            # API may return embeddings out of order; sort by index.
            sorted_data = sorted(response.data, key=lambda d: d.index)
            return [item.embedding for item in sorted_data]
        except Exception:
            logger.warning(
                "embedding_service.embed_batch_failed",
                model=self.config.model,
                batch_size=len(texts),
                exc_info=True,
            )
            return [[] for _ in texts]


class NullEmbeddingService:
    """No-op embedding service for when embeddings are not configured."""

    async def embed(self, text: str) -> list[float]:  # noqa: ARG002
        """Always returns an empty list."""
        return []

    async def embed_batch(
        self, texts: list[str],
    ) -> list[list[float]]:
        """Always returns empty lists."""
        return [[] for _ in texts]
