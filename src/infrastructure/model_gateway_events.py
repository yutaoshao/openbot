"""Logging and event publication for model gateway requests."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from src.core.logging import get_logger
from src.infrastructure.model_usage import llm_completed_fields, model_request_payload

if TYPE_CHECKING:
    from src.core.config import ModelConfig
    from src.infrastructure.event_bus import EventBus
    from src.infrastructure.model_provider_selector import ProviderAttempt
    from src.infrastructure.model_types import Usage

logger = get_logger(__name__)


async def record_model_completion(
    *,
    event_bus: EventBus,
    provider_attempt: ProviderAttempt,
    model: str,
    usage: Usage,
    latency_ms: int,
    cost_usd: float,
) -> None:
    usage.cost_usd = cost_usd
    route_fields = _route_fields(provider_attempt)
    logger.info(
        "llm_completed",
        **llm_completed_fields(
            provider=provider_attempt.key,
            model=model,
            usage=usage,
            latency_ms=latency_ms,
            **route_fields,
        ),
    )
    await event_bus.publish(
        "model.request",
        model_request_payload(
            provider=provider_attempt.key,
            model=model,
            usage=usage,
            latency_ms=latency_ms,
            **route_fields,
        ),
    )


async def handle_model_retry(
    *,
    config: ModelConfig,
    provider_key: str,
    attempt: int,
    error: Exception,
    status: str,
) -> None:
    delay = config.retry_base_delay * (2**attempt)
    logger.warning(
        "llm_requested",
        surface="operational",
        status=status,
        provider=provider_key,
        attempt=attempt + 1,
        max_retries=config.max_retries,
        delay=delay,
        error=str(error),
    )
    if attempt < config.max_retries - 1:
        await asyncio.sleep(delay)


def _route_fields(provider_attempt: ProviderAttempt) -> dict[str, str]:
    route_fields: dict[str, str] = {}
    if provider_attempt.route_tier is not None:
        route_fields["route_tier"] = provider_attempt.route_tier
    if provider_attempt.route_reason is not None:
        route_fields["route_reason"] = provider_attempt.route_reason
    return route_fields
