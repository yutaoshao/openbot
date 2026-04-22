"""Text embedding generation for vector search.

Supports multiple providers:
- openai_compatible: DashScope text-embedding-v4, SiliconFlow, Volcengine, etc.
- dashscope: DashScope native SDK (required for multimodal models like qwen3-vl-embedding)
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from src.core.logging import get_logger

if TYPE_CHECKING:
    from src.core.config import EmbeddingConfig

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Provider protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Interface for embedding provider implementations."""

    async def embed(self, text: str) -> list[float]: ...

    async def embed_batch(self, texts: list[str]) -> list[list[float]]: ...


# ---------------------------------------------------------------------------
# OpenAI-compatible provider
# ---------------------------------------------------------------------------


class OpenAIEmbeddingProvider:
    """Embedding via OpenAI-compatible /v1/embeddings endpoint.

    Works with DashScope (text-embedding-v4), SiliconFlow, Volcengine, etc.
    """

    def __init__(self, config: EmbeddingConfig) -> None:
        from openai import AsyncOpenAI

        self._model = config.model
        self._dimensions = config.dimensions
        self._client = AsyncOpenAI(
            api_key=config.api_key,
            base_url=config.base_url,
        )

    async def embed(self, text: str) -> list[float]:
        response = await self._client.embeddings.create(
            model=self._model,
            input=text,
            dimensions=self._dimensions,
        )
        return response.data[0].embedding

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        response = await self._client.embeddings.create(
            model=self._model,
            input=texts,
            dimensions=self._dimensions,
        )
        sorted_data = sorted(response.data, key=lambda d: d.index)
        return [item.embedding for item in sorted_data]


# ---------------------------------------------------------------------------
# DashScope native provider
# ---------------------------------------------------------------------------


class DashScopeEmbeddingProvider:
    """Embedding via DashScope native SDK.

    Required for multimodal models (qwen3-vl-embedding, qwen2.5-vl-embedding)
    that do not support the OpenAI-compatible endpoint.
    Also works with text-only models (text-embedding-v4) via TextEmbedding.
    """

    def __init__(self, config: EmbeddingConfig) -> None:
        import dashscope

        self._model = config.model
        self._dimensions = config.dimensions
        self._api_key = config.api_key
        self._is_multimodal = "vl" in config.model.lower()

        # Set API key for dashscope SDK
        dashscope.api_key = self._api_key

    async def embed(self, text: str) -> list[float]:
        if self._is_multimodal:
            return await self._embed_multimodal(text)
        return await self._embed_text(text)

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        if self._is_multimodal:
            # MultiModalEmbedding supports batch via list of dicts
            return await self._embed_multimodal_batch(texts)
        return await self._embed_text_batch(texts)

    async def _embed_text(self, text: str) -> list[float]:
        """Call dashscope.TextEmbedding.call() in a thread."""
        from http import HTTPStatus

        import dashscope

        def _call() -> list[float]:
            resp = dashscope.TextEmbedding.call(
                model=self._model,
                input=text,
                dimension=self._dimensions,
                api_key=self._api_key,
            )
            if resp.status_code != HTTPStatus.OK:
                raise RuntimeError(f"DashScope TextEmbedding failed: {resp.code} {resp.message}")
            return resp.output["embeddings"][0]["embedding"]

        return await asyncio.to_thread(_call)

    async def _embed_text_batch(
        self,
        texts: list[str],
    ) -> list[list[float]]:
        """Batch text embedding (max 10 per call)."""
        from http import HTTPStatus

        import dashscope

        def _call() -> list[list[float]]:
            resp = dashscope.TextEmbedding.call(
                model=self._model,
                input=texts[:10],  # SDK limit: 10 per call
                dimension=self._dimensions,
                api_key=self._api_key,
            )
            if resp.status_code != HTTPStatus.OK:
                raise RuntimeError(
                    f"DashScope TextEmbedding batch failed: {resp.code} {resp.message}"
                )
            embeddings = resp.output["embeddings"]
            return [e["embedding"] for e in embeddings]

        return await asyncio.to_thread(_call)

    async def _embed_multimodal(self, text: str) -> list[float]:
        """Call dashscope.MultiModalEmbedding.call() for text input."""
        from http import HTTPStatus

        import dashscope

        def _call() -> list[float]:
            resp = dashscope.MultiModalEmbedding.call(
                model=self._model,
                input=[{"text": text}],
                dimension=self._dimensions,
                api_key=self._api_key,
            )
            if resp.status_code != HTTPStatus.OK:
                raise RuntimeError(
                    f"DashScope MultiModalEmbedding failed: {resp.code} {resp.message}"
                )
            return resp.output["embeddings"][0]["embedding"]

        return await asyncio.to_thread(_call)

    async def _embed_multimodal_batch(
        self,
        texts: list[str],
    ) -> list[list[float]]:
        """Batch multimodal embedding (sequential, one per call)."""
        results: list[list[float]] = []
        for text in texts:
            embedding = await self._embed_multimodal(text)
            results.append(embedding)
        return results


# ---------------------------------------------------------------------------
# Unified service
# ---------------------------------------------------------------------------

_PROVIDERS: dict[str, type] = {
    "openai_compatible": OpenAIEmbeddingProvider,
    "dashscope": DashScopeEmbeddingProvider,
}


class EmbeddingService:
    """Unified embedding service dispatching to the configured provider."""

    def __init__(self, config: EmbeddingConfig) -> None:
        self.config = config
        self._provider: Any = None

        if config.enabled:
            provider_cls = _PROVIDERS.get(config.provider)
            if not provider_cls:
                raise ValueError(
                    f"Unknown embedding provider: '{config.provider}'. "
                    f"Supported: {', '.join(_PROVIDERS)}"
                )
            self._provider = provider_cls(config)
            logger.info(
                "embedding_service.init",
                provider=config.provider,
                model=config.model,
                dimensions=config.dimensions,
            )
        else:
            logger.info("embedding_service.disabled")

    async def embed(self, text: str) -> list[float]:
        """Generate an embedding vector for a single text.

        Returns an empty list when the service is disabled or on error.
        """
        if not self.config.enabled or self._provider is None:
            return []

        try:
            return await self._provider.embed(text)
        except Exception:
            logger.warning(
                "embedding_service.embed_failed",
                provider=self.config.provider,
                model=self.config.model,
                text_len=len(text),
                exc_info=True,
            )
            return []

    async def embed_batch(
        self,
        texts: list[str],
    ) -> list[list[float]]:
        """Generate embedding vectors for a batch of texts.

        Returns a list of empty lists (one per input text) on failure.
        """
        if not self.config.enabled or self._provider is None:
            return [[] for _ in texts]

        if not texts:
            return []

        try:
            return await self._provider.embed_batch(texts)
        except Exception:
            logger.warning(
                "embedding_service.embed_batch_failed",
                provider=self.config.provider,
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
        self,
        texts: list[str],
    ) -> list[list[float]]:
        """Always returns empty lists."""
        return [[] for _ in texts]
