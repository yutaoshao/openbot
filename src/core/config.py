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


class ModelProviderConfig(BaseModel):
    """Single model provider configuration."""

    provider: Literal["anthropic", "openai_compatible"] = "anthropic"
    model: str = "claude-sonnet-4-20250514"
    base_url: str | None = None
    max_tokens: int = 4096
    temperature: float = 0.7
    # Name of the environment variable that holds the API key
    api_key_env: str = "ANTHROPIC_API_KEY"
    # Connection timeout: max seconds to establish TCP connection (fast-fail)
    connect_timeout: float = 30.0
    # Read timeout: max seconds to wait for first token from model
    # Set higher for slow-thinking models (DeepSeek R1, o1, etc.)
    read_timeout: float = 300.0
    # Pricing per 1M tokens (for cost tracking)
    pricing_input: float = 0.0
    pricing_output: float = 0.0

    @property
    def api_key(self) -> str:
        """Resolve API key from environment variable."""
        return os.environ.get(self.api_key_env, "")


class ModelConfig(BaseModel):
    """Model gateway configuration."""

    primary: ModelProviderConfig = Field(default_factory=ModelProviderConfig)
    fallback: ModelProviderConfig | None = None
    max_retries: int = 3
    retry_base_delay: float = 1.0


class TelegramConfig(BaseModel):
    """Telegram bot configuration."""

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


class FeishuConfig(BaseModel):
    """Feishu (Lark) bot configuration."""

    enabled: bool = False
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


class StorageConfig(BaseModel):
    """Database storage configuration."""

    db_path: str = "data/openbot.db"
    workspace_path: str = "data/workspace"

    @field_validator("db_path", "workspace_path", mode="before")
    @classmethod
    def _expand_path(cls, value: str) -> str:
        """Expand ``~`` and env vars while preserving relative paths."""
        if not isinstance(value, str):
            return value
        return str(Path(os.path.expandvars(value)).expanduser())


class ApiConfig(BaseModel):
    """REST/WebSocket API server configuration."""

    enabled: bool = True
    host: str = "127.0.0.1"
    port: int = 8000
    cors_origins: list[str] = Field(
        default_factory=lambda: ["*"],
        description="Allowed CORS origins. Use specific origins in production.",
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
    # Max cost in dollars for a single agent run (0 = no limit)
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
