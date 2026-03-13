"""Pydantic-based configuration system.

Loads from config.yaml, overridden by environment variables.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ModelProviderConfig(BaseModel):
    """Single model provider configuration."""

    provider: Literal["anthropic", "openai"] = "anthropic"
    model: str = "claude-sonnet-4-20250514"
    api_key: str = ""
    max_tokens: int = 4096
    temperature: float = 0.7


class ModelConfig(BaseModel):
    """Model gateway configuration."""

    primary: ModelProviderConfig = Field(default_factory=ModelProviderConfig)
    fallback: ModelProviderConfig | None = None
    max_retries: int = 3
    retry_base_delay: float = 1.0


class TelegramConfig(BaseModel):
    """Telegram bot configuration."""

    bot_token: str = ""
    mode: Literal["polling", "webhook"] = "polling"
    webhook_url: str | None = None
    allowed_user_ids: list[int] = Field(default_factory=list)


class StorageConfig(BaseModel):
    """Database storage configuration."""

    db_path: str = "data/openbot.db"


class LogConfig(BaseModel):
    """Logging configuration."""

    level: str = "INFO"
    format: Literal["console", "json"] = "console"


class AgentConfig(BaseModel):
    """Agent core configuration."""

    max_iterations: int = 10
    system_prompt: str = ""
    token_budget: int = 8000


class AppConfig(BaseSettings):
    """Root application configuration.

    Priority: environment variables > config.yaml > defaults
    """

    model_config = SettingsConfigDict(
        env_prefix="OPENBOT_",
        env_nested_delimiter="__",
    )

    model: ModelConfig = Field(default_factory=ModelConfig)
    telegram: TelegramConfig = Field(default_factory=TelegramConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    log: LogConfig = Field(default_factory=LogConfig)
    agent: AgentConfig = Field(default_factory=AgentConfig)

    # Direct env var mappings for convenience
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    telegram_bot_token: str = ""
    tavily_api_key: str = ""


def load_config(config_path: str = "config.yaml") -> AppConfig:
    """Load configuration from YAML file, then override with env vars."""
    yaml_data = {}
    path = Path(config_path)
    if path.exists():
        with open(path) as f:
            yaml_data = yaml.safe_load(f) or {}

    config = AppConfig(**yaml_data)

    # Map convenience env vars to nested config
    if config.anthropic_api_key and not config.model.primary.api_key:
        config.model.primary.api_key = config.anthropic_api_key
    if config.telegram_bot_token and not config.telegram.bot_token:
        config.telegram.bot_token = config.telegram_bot_token

    return config
