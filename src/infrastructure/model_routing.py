"""Deterministic model routing for the model gateway."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.core.model_config import ModelRoutingConfig, RouteTier


@dataclass(frozen=True)
class RouteRequest:
    """Inputs used by the deterministic route classifier."""

    input_text: str
    tool_names: tuple[str, ...] = ()
    purpose: str = "agent"


@dataclass(frozen=True)
class RouteDecision:
    """Selected model tier and the rule that selected it."""

    tier: RouteTier
    reason: str
    matched_rules: tuple[str, ...] = field(default_factory=tuple)


class ModelRouter:
    """Rule-based classifier that never calls an LLM."""

    def __init__(self, config: ModelRoutingConfig) -> None:
        self._config = config

    def decide(self, request: RouteRequest) -> RouteDecision:
        """Return a deterministic route decision for one request."""
        if not self._config.enabled:
            return RouteDecision(
                tier=self._config.default_tier,
                reason="routing_disabled",
                matched_rules=("routing_disabled",),
            )
        complex_decision = self._complex_decision(request)
        if complex_decision is not None:
            return complex_decision
        simple_decision = self._simple_decision(request)
        if simple_decision is not None:
            return simple_decision
        return RouteDecision(
            tier=self._config.default_tier,
            reason="default_tier",
            matched_rules=(f"default_tier:{self._config.default_tier}",),
        )

    def _complex_decision(self, request: RouteRequest) -> RouteDecision | None:
        text_length = len(request.input_text)
        rules = self._config.rules
        if text_length >= rules.complex_min_chars:
            return RouteDecision("complex", "long_prompt", (f"chars:{text_length}",))
        tool_count = len(set(request.tool_names))
        if tool_count >= rules.tool_count_complex_threshold:
            return RouteDecision("complex", "tool_count", (f"tool_count:{tool_count}",))
        return _keyword_decision(
            tier="complex",
            reason="complex_keyword",
            text=request.input_text,
            keywords=rules.complex_keywords,
        )

    def _simple_decision(self, request: RouteRequest) -> RouteDecision | None:
        if len(request.input_text) > self._config.rules.simple_max_chars:
            return None
        keyword_decision = _keyword_decision(
            tier="simple",
            reason="simple_keyword",
            text=request.input_text,
            keywords=self._config.rules.simple_keywords,
        )
        if keyword_decision is not None:
            return keyword_decision
        if not request.tool_names:
            return RouteDecision("simple", "short_prompt", ("short_prompt",))
        return None


def _keyword_decision(
    *,
    tier: RouteTier,
    reason: str,
    text: str,
    keywords: list[str],
) -> RouteDecision | None:
    lowered = text.lower()
    for keyword in keywords:
        if keyword.lower() in lowered:
            return RouteDecision(tier, reason, (f"{reason}:{keyword}",))
    return None
