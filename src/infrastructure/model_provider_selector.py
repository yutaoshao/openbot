"""Provider selection for primary/fallback and routed model calls."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.core.model_config import ModelConfig, ModelProviderConfig, RouteTier


@dataclass(frozen=True)
class ProviderAttempt:
    """One provider attempt for a model request."""

    key: str
    route_tier: RouteTier | None = None
    route_reason: str | None = None


class ModelProviderSelector:
    """Build provider attempts without owning provider clients."""

    def __init__(self, config: ModelConfig) -> None:
        self._config = config

    def provider_configs(self) -> dict[str, ModelProviderConfig]:
        if self._config.routing.enabled:
            return self._routed_provider_configs()
        return self._legacy_provider_configs()

    def provider_config(self, provider_key: str) -> ModelProviderConfig | None:
        return self.provider_configs().get(provider_key)

    def attempts(
        self,
        *,
        route_tier: RouteTier | None = None,
        route_reason: str | None = None,
    ) -> list[ProviderAttempt]:
        if not self._config.routing.enabled:
            return self._legacy_attempts()
        selected_tier = route_tier or self._config.routing.default_tier
        if selected_tier not in self._config.routing.tiers:
            raise ValueError(f"Unknown route_tier '{selected_tier}'")
        reason = route_reason or "default_route_tier"
        attempts = [ProviderAttempt(f"route:{selected_tier}", selected_tier, reason)]
        if self._config.fallback is not None:
            attempts.append(ProviderAttempt("fallback", selected_tier, reason))
        return attempts

    def _legacy_provider_configs(self) -> dict[str, ModelProviderConfig]:
        configs = {"primary": self._config.primary}
        if self._config.fallback is not None:
            configs["fallback"] = self._config.fallback
        return configs

    def _routed_provider_configs(self) -> dict[str, ModelProviderConfig]:
        configs = {
            f"route:{tier}": provider_config
            for tier, provider_config in self._config.routing.tiers.items()
        }
        if self._config.fallback is not None:
            configs["fallback"] = self._config.fallback
        return configs

    def _legacy_attempts(self) -> list[ProviderAttempt]:
        attempts = [ProviderAttempt("primary")]
        if self._config.fallback is not None:
            attempts.append(ProviderAttempt("fallback"))
        return attempts
