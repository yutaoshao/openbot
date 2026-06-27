"""Model gateway configuration models."""

from __future__ import annotations

import os
from typing import Literal

from pydantic import BaseModel, Field, model_validator

RouteTier = Literal["simple", "complex"]
ReasoningEffort = Literal["low", "medium", "high", "xhigh"]
ModelVerbosity = Literal["low", "medium", "high"]


class ModelProviderConfig(BaseModel):
    """Single model provider configuration."""

    provider: Literal["anthropic", "openai_compatible", "openai_responses"] = "anthropic"
    model: str = "claude-sonnet-4-20250514"
    base_url: str | None = None
    max_tokens: int = 4096
    temperature: float = 0.7
    api_key_env: str = "ANTHROPIC_API_KEY"
    pricing_input: float | None = None
    pricing_output: float | None = None
    connect_timeout: float = 30.0
    read_timeout: float = 300.0
    reasoning_effort: ReasoningEffort = "medium"
    verbosity: ModelVerbosity = "low"

    @property
    def api_key(self) -> str:
        """Resolve API key from environment variable."""
        return os.environ.get(self.api_key_env, "")

    @model_validator(mode="after")
    def _validate_provider_specific_fields(self) -> ModelProviderConfig:
        if self.provider != "openai_responses":
            return self
        if self.base_url is not None and not self.base_url.rstrip("/").endswith("/v1"):
            raise ValueError("openai_responses base_url must end with /v1")
        if not self.api_key_env.strip():
            raise ValueError("openai_responses api_key_env must not be empty")
        return self


class ModelRoutingRulesConfig(BaseModel):
    """Deterministic routing thresholds and keyword rules."""

    simple_max_chars: int = 120
    complex_min_chars: int = 600
    tool_count_complex_threshold: int = 2
    simple_keywords: list[str] = Field(
        default_factory=lambda: [
            "translate",
            "翻译",
            "summarize",
            "总结",
            "explain",
            "解释",
        ]
    )
    complex_keywords: list[str] = Field(
        default_factory=lambda: [
            "debug",
            "bug",
            "implement",
            "refactor",
            "architecture",
            "调试",
            "修复",
            "实现",
            "重构",
            "架构",
        ]
    )


class ModelRoutingConfig(BaseModel):
    """Optional model routing configuration."""

    enabled: bool = False
    default_tier: RouteTier = "complex"
    tiers: dict[RouteTier, ModelProviderConfig] = Field(default_factory=dict)
    rules: ModelRoutingRulesConfig = Field(default_factory=ModelRoutingRulesConfig)

    @model_validator(mode="after")
    def _validate_enabled_tiers(self) -> ModelRoutingConfig:
        if not self.enabled:
            return self
        missing = {"simple", "complex"} - set(self.tiers)
        if missing:
            joined = ", ".join(sorted(missing))
            raise ValueError(
                f"routing enabled requires simple and complex tiers; missing: {joined}",
            )
        if self.default_tier not in self.tiers:
            raise ValueError(f"default_tier '{self.default_tier}' is not configured in tiers")
        return self


class ModelConfig(BaseModel):
    """Model gateway configuration."""

    primary: ModelProviderConfig = Field(default_factory=ModelProviderConfig)
    fallback: ModelProviderConfig | None = None
    routing: ModelRoutingConfig = Field(default_factory=ModelRoutingConfig)
    max_retries: int = 3
    retry_base_delay: float = 1.0
