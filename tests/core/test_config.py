from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from src.core.config import (
    ApiConfig,
    FeishuConfig,
    ModelConfig,
    ModelProviderConfig,
    StorageConfig,
    TelegramConfig,
    WeChatConfig,
)


def test_storage_config_expands_user_in_db_path() -> None:
    config = StorageConfig(db_path="~/Project/openbot/openbot.db")

    assert config.db_path == str(Path("~/Project/openbot/openbot.db").expanduser())


def test_wechat_config_expands_user_in_state_path() -> None:
    config = WeChatConfig(state_path="~/data/wechat/ilink_state.json")

    assert config.state_path == str(Path("~/data/wechat/ilink_state.json").expanduser())


def test_feishu_long_connection_requires_only_app_credentials(monkeypatch) -> None:
    monkeypatch.setenv("FEISHU_APP_ID", "cli_test")
    monkeypatch.setenv("FEISHU_APP_SECRET", "secret_test")
    monkeypatch.delenv("FEISHU_VERIFICATION_TOKEN", raising=False)
    monkeypatch.delenv("FEISHU_ENCRYPT_KEY", raising=False)

    config = FeishuConfig(enabled=True, mode="long_connection")

    assert config.missing_required_env_vars() == []


def test_feishu_webhook_requires_token_and_encrypt_key(monkeypatch) -> None:
    monkeypatch.setenv("FEISHU_APP_ID", "cli_test")
    monkeypatch.setenv("FEISHU_APP_SECRET", "secret_test")
    monkeypatch.delenv("FEISHU_VERIFICATION_TOKEN", raising=False)
    monkeypatch.delenv("FEISHU_ENCRYPT_KEY", raising=False)

    config = FeishuConfig(enabled=True, mode="webhook")

    assert config.missing_required_env_vars() == [
        "FEISHU_VERIFICATION_TOKEN",
        "FEISHU_ENCRYPT_KEY",
    ]


def test_telegram_disabled_requires_no_token(monkeypatch) -> None:
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)

    config = TelegramConfig(enabled=False)

    assert config.missing_required_env_vars() == []


def test_telegram_enabled_requires_token(monkeypatch) -> None:
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)

    config = TelegramConfig(enabled=True)

    assert config.missing_required_env_vars() == ["TELEGRAM_BOT_TOKEN"]


def test_api_config_defaults_to_local_only() -> None:
    config = ApiConfig()

    assert config.local_only is True


def test_model_provider_accepts_pricing_metadata() -> None:
    config = ModelProviderConfig(pricing_input=0.6, pricing_output=3.0)

    assert config.pricing_input == 0.6
    assert config.pricing_output == 3.0


def test_model_routing_disabled_accepts_legacy_model_config() -> None:
    config = ModelConfig()

    assert config.routing.enabled is False
    assert config.routing.default_tier == "complex"
    assert config.routing.tiers == {}


def test_model_routing_accepts_responses_reasoning_tiers_when_disabled() -> None:
    config = ModelConfig(
        routing={
            "enabled": False,
            "default_tier": "complex",
            "tiers": {
                "simple": {
                    "provider": "openai_responses",
                    "model": "gpt-5.5",
                    "reasoning_effort": "medium",
                    "verbosity": "low",
                },
                "complex": {
                    "provider": "openai_responses",
                    "model": "gpt-5.5",
                    "reasoning_effort": "xhigh",
                    "verbosity": "low",
                },
            },
        },
    )

    assert config.routing.enabled is False
    assert config.routing.tiers["simple"].reasoning_effort == "medium"
    assert config.routing.tiers["complex"].reasoning_effort == "xhigh"
    assert config.routing.tiers["complex"].verbosity == "low"


def test_model_accepts_active_responses_provider() -> None:
    config = ModelConfig(
        primary={
            "provider": "openai_responses",
            "model": "gpt-5.5",
            "base_url": "https://api.example.com/v1",
            "api_key_env": "OPENAI_API_KEY",
        },
    )

    assert config.primary.provider == "openai_responses"


def test_responses_provider_requires_sdk_base_url_root() -> None:
    with pytest.raises(ValidationError, match="openai_responses base_url must end with /v1"):
        ModelProviderConfig(
            provider="openai_responses",
            model="gpt-5.5",
            base_url="https://api.example.com",
        )


def test_responses_provider_requires_api_key_env_name() -> None:
    with pytest.raises(ValidationError, match="openai_responses api_key_env must not be empty"):
        ModelProviderConfig(
            provider="openai_responses",
            model="gpt-5.5",
            api_key_env="",
        )


def test_model_routing_enabled_requires_simple_and_complex_tiers() -> None:
    with pytest.raises(ValidationError, match="simple.*complex"):
        ModelConfig(
            routing={
                "enabled": True,
                "tiers": {
                    "simple": {
                        "provider": "openai_compatible",
                        "model": "fast-model",
                    },
                },
            },
        )
