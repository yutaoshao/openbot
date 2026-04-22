"""Pydantic request/response schemas for REST API."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

MAX_CHAT_MESSAGE_CHARS = 32000


class ChatRequest(BaseModel):
    """Request payload for ``POST /api/chat``."""

    message: str = Field(
        min_length=1,
        max_length=MAX_CHAT_MESSAGE_CHARS,
        description="User message text",
    )
    conversation_id: str = Field(
        default="",
        description="Optional conversation id for memory continuity",
    )
    platform: str = Field(
        default="web",
        description="Source platform label used by the agent pipeline",
    )

    @field_validator("message")
    @classmethod
    def _validate_message(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("message must not be blank")
        return stripped


class ChatResponse(BaseModel):
    """Response payload for ``POST /api/chat``."""

    reply: str
    conversation_id: str
    model: str
    latency_ms: int
    tokens_in: int
    tokens_out: int


class HealthResponse(BaseModel):
    """Response payload for health checks."""

    status: str
    runtime: dict[str, dict[str, str | bool | list[str] | None]] | None = None


class IdentityBindRequest(BaseModel):
    """Bind a platform account to a canonical internal user id."""

    user_id: str | None = Field(default=None, min_length=1)
    platform: str = Field(min_length=1)
    platform_user_id: str = Field(min_length=1)


class IdentityItem(BaseModel):
    """Stored user identity mapping."""

    id: str
    user_id: str
    platform: str
    platform_user_id: str
    created_at: str
    updated_at: str


class ConversationSummary(BaseModel):
    """Conversation item returned by list endpoint."""

    id: str
    title: str | None = None
    summary: str | None = None
    platform: str
    created_at: str
    updated_at: str
    message_count: int


class MessageItem(BaseModel):
    """Message item returned by conversation detail endpoint."""

    id: str
    conversation_id: str
    role: str
    content: str
    model: str | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    latency_ms: int | None = None
    tool_calls: list[dict] | None = None
    metadata: dict | None = None
    created_at: str


class ConversationDetail(BaseModel):
    """Conversation detail including message history."""

    conversation: ConversationSummary
    messages: list[MessageItem]


class KnowledgeCreateRequest(BaseModel):
    """Create knowledge item payload."""

    category: str
    content: str
    tags: list[str] | None = None
    priority: str = "P1"
    confidence: float | None = None
    source_conversation_id: str | None = None
    expires_at: str | None = None


class KnowledgeUpdateRequest(BaseModel):
    """Partial update payload for knowledge item."""

    category: str | None = None
    content: str | None = None
    tags: list[str] | None = None
    priority: str | None = None
    confidence: float | None = None
    expires_at: str | None = None


class KnowledgeItem(BaseModel):
    """Knowledge item response model."""

    id: str
    source_conversation_id: str | None = None
    category: str
    content: str
    tags: list[str] | None = None
    priority: str
    confidence: float | None = None
    access_count: int
    created_at: str
    updated_at: str
    expires_at: str | None = None


class ToolStatusItem(BaseModel):
    """Tool status response model."""

    name: str
    description: str
    category: str
    visibility: str | None = None
    enabled: bool
    config: dict
    last_used: str | None = None


class ToolConfigUpdateRequest(BaseModel):
    """Mutable runtime config payload for tools."""

    enabled: bool | None = None
    config: dict | None = None


class ScheduleCreateRequest(BaseModel):
    """Create schedule payload."""

    name: str
    prompt: str
    cron: str
    target_platform: str | None = None
    target_id: str | None = None
    status: str = "active"
    next_run_at: str | None = None


class ScheduleUpdateRequest(BaseModel):
    """Partial schedule update payload."""

    name: str | None = None
    prompt: str | None = None
    cron: str | None = None
    target_platform: str | None = None
    target_id: str | None = None
    status: str | None = None
    last_run_at: str | None = None
    next_run_at: str | None = None


class ScheduleItem(BaseModel):
    """Schedule response model."""

    id: str
    name: str
    prompt: str
    cron: str
    target_platform: str | None = None
    target_id: str | None = None
    status: str
    last_run_at: str | None = None
    next_run_at: str | None = None
    created_at: str
    updated_at: str


class TelegramSettingsPatch(BaseModel):
    """Editable Telegram settings surfaced in the dashboard."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool | None = None
    mode: Literal["polling", "webhook"] | None = None
    enable_streaming: bool | None = None


class ModelSettingsPatch(BaseModel):
    """Editable model gateway settings surfaced in the dashboard."""

    model_config = ConfigDict(extra="forbid")

    max_retries: int | None = Field(default=None, ge=0)


class SettingsUpdateRequest(BaseModel):
    """Restricted settings patch accepted by ``PUT /api/settings``."""

    model_config = ConfigDict(extra="forbid")

    telegram: TelegramSettingsPatch | None = None
    model: ModelSettingsPatch | None = None
