"""Pydantic-based configuration system.

Loading order:
1. config.yaml  -- all non-secret settings (model, telegram mode, log level, etc.)
2. .env         -- all secret keys (API keys, bot tokens)

config.yaml uses `api_key_env` to declare which .env variable holds the key.
This avoids hardcoding provider-specific env var names in Python code.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field, field_validator

from src.core.model_config import (
    ModelConfig,
    ModelProviderConfig,
    ModelRoutingConfig,
    ModelRoutingRulesConfig,
)

__all__ = [
    "AgentConfig",
    "ApiConfig",
    "AppConfig",
    "EmbeddingConfig",
    "FeishuConfig",
    "LogConfig",
    "ModelConfig",
    "ModelProviderConfig",
    "ModelRoutingConfig",
    "ModelRoutingRulesConfig",
    "RerankerConfig",
    "SchedulerConfig",
    "StorageConfig",
    "TelegramConfig",
    "WeChatConfig",
    "load_config",
]


def _expand_user_path(value: str) -> str:
    """Expand ``~`` and env vars while preserving relative paths."""
    return str(Path(os.path.expandvars(value)).expanduser())


class TelegramConfig(BaseModel):
    """Telegram bot configuration."""

    enabled: bool = True
    mode: Literal["polling", "webhook"] = "polling"
    bot_token_env: str = "TELEGRAM_BOT_TOKEN"
    webhook_url: str | None = None
    webhook_secret: str | None = None
    allowed_user_ids: list[int] = Field(default_factory=list)
    stream_throttle: float = 0.5  # seconds between draft updates
    enable_streaming: bool = False

    @property
    def bot_token(self) -> str:
        """Resolve bot token from environment variable."""
        return os.environ.get(self.bot_token_env, "")

    def missing_required_env_vars(self) -> list[str]:
        """Return required Telegram env vars that are not configured."""
        if not self.enabled:
            return []
        required = ((self.bot_token_env, self.bot_token),)
        return [env_name for env_name, value in required if not value]


class FeishuConfig(BaseModel):
    """Feishu (Lark) bot configuration."""

    enabled: bool = False
    mode: Literal["webhook", "long_connection"] = "webhook"
    app_id_env: str = "FEISHU_APP_ID"
    app_secret_env: str = "FEISHU_APP_SECRET"
    verification_token_env: str = "FEISHU_VERIFICATION_TOKEN"
    encrypt_key_env: str = "FEISHU_ENCRYPT_KEY"

    @property
    def app_id(self) -> str:
        return os.environ.get(self.app_id_env, "")

    @property
    def app_secret(self) -> str:
        return os.environ.get(self.app_secret_env, "")

    @property
    def verification_token(self) -> str:
        return os.environ.get(self.verification_token_env, "")

    @property
    def encrypt_key(self) -> str:
        return os.environ.get(self.encrypt_key_env, "")

    def missing_required_env_vars(self) -> list[str]:
        """Return required Feishu env vars that are not configured."""
        required = [
            (self.app_id_env, self.app_id),
            (self.app_secret_env, self.app_secret),
        ]
        if self.mode == "webhook":
            required.extend(
                [
                    (self.verification_token_env, self.verification_token),
                    (self.encrypt_key_env, self.encrypt_key),
                ]
            )
        return [env_name for env_name, value in required if not value]


class StorageConfig(BaseModel):
    """Database storage configuration."""

    db_path: str = "data/openbot.db"
    workspace_path: str = "data/workspace"

    @field_validator("db_path", "workspace_path", mode="before")
    @classmethod
    def _expand_path(cls, value: str) -> str:
        if not isinstance(value, str):
            return value
        return _expand_user_path(value)


class WeChatConfig(BaseModel):
    """WeChat personal-account iLink adapter configuration."""

    enabled: bool = False
    mode: Literal["ilink_polling"] = "ilink_polling"
    state_path: str = "data/wechat/ilink_state.json"
    api_base_url: str = "https://ilinkai.weixin.qq.com"
    poll_interval: float = 2.0
    max_backoff: float = 30.0

    @field_validator("state_path", mode="before")
    @classmethod
    def _expand_state_path(cls, value: str) -> str:
        if not isinstance(value, str):
            return value
        return _expand_user_path(value)


class ApiConfig(BaseModel):
    """REST/WebSocket API server configuration."""

    enabled: bool = True
    host: str = "127.0.0.1"
    port: int = 8000
    local_only: bool = True
    cors_origins: list[str] = Field(
        default_factory=lambda: [
            "http://127.0.0.1:8000",
            "http://localhost:8000",
            "http://127.0.0.1:5173",
            "http://localhost:5173",
        ],
        description="Allowed CORS origins. Explicitly configure production origins.",
    )
    serve_frontend: bool = True
    frontend_dist: str = "frontend/dist"


class SchedulerConfig(BaseModel):
    """Background scheduler configuration."""

    timezone: str = ""


class LogConfig(BaseModel):
    """Logging configuration."""

    level: str = "INFO"
    format: Literal["console", "json"] = "console"
    file: str | None = None  # e.g. "data/logs/openbot.log"
    max_bytes: int = 10 * 1024 * 1024  # 10 MB
    backup_count: int = 5
    otlp_endpoint: str | None = None  # e.g. "http://localhost:4317"


class AgentConfig(BaseModel):
    """Agent core configuration."""

    max_iterations: int = 50
    system_prompt: str = ""
    token_budget: int = 8000
    # Max total seconds for a single agent run (0 = no limit)
    task_timeout: int = 0
    # Max seconds for a single tool call (0 = no limit)
    tool_timeout: float = 120.0
    # Max total cost in USD for a single task (0 = no limit)
    max_task_cost: float = 0.0
    # Consecutive identical tool calls before declaring "stuck" (0 = disable)
    stuck_detection_threshold: int = 3


class EmbeddingConfig(BaseModel):
    """Embedding service configuration.

    Providers:
    - openai_compatible: DashScope text-embedding-v4, SiliconFlow, etc.
    - dashscope: DashScope native SDK (required for qwen3-vl-embedding)
    """

    enabled: bool = False
    provider: Literal["openai_compatible", "dashscope"] = "openai_compatible"
    model: str = "text-embedding-v4"
    base_url: str | None = None
    api_key_env: str = "DASHSCOPE_API_KEY"
    dimensions: int = 1024

    @property
    def api_key(self) -> str:
        """Resolve API key from environment variable."""
        return os.environ.get(self.api_key_env, "")


class RerankerConfig(BaseModel):
    """Reranker service configuration.

    Uses SiliconFlow-style /v1/rerank endpoint (also compatible with
    Jina, Cohere, and other providers that implement the same API).
    """

    enabled: bool = False
    model: str = "Qwen/Qwen3-Reranker-8B"
    base_url: str = "https://api.siliconflow.cn/v1"
    api_key_env: str = "SILICONFLOW_API_KEY"
    top_n: int = 5

    @property
    def api_key(self) -> str:
        """Resolve API key from environment variable."""
        return os.environ.get(self.api_key_env, "")


class AppConfig(BaseModel):
    """Root application configuration."""

    model: ModelConfig = Field(default_factory=ModelConfig)
    telegram: TelegramConfig = Field(default_factory=TelegramConfig)
    feishu: FeishuConfig = Field(default_factory=FeishuConfig)
    wechat: WeChatConfig = Field(default_factory=WeChatConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    api: ApiConfig = Field(default_factory=ApiConfig)
    scheduler: SchedulerConfig = Field(default_factory=SchedulerConfig)
    log: LogConfig = Field(default_factory=LogConfig)
    agent: AgentConfig = Field(default_factory=AgentConfig)
    embedding: EmbeddingConfig = Field(default_factory=EmbeddingConfig)
    reranker: RerankerConfig = Field(default_factory=RerankerConfig)


def load_config(config_path: str = "config.yaml") -> AppConfig:
    """Load configuration.

    1. load_dotenv() -- reads .env into os.environ
    2. Parse config.yaml -- all non-secret settings
    3. Secrets are resolved lazily via property accessors (api_key, bot_token)
    """
    load_dotenv()

    yaml_data: dict = {}
    path = Path(config_path)
    if path.exists():
        with open(path) as f:
            yaml_data = yaml.safe_load(f) or {}

    return AppConfig(**yaml_data)
