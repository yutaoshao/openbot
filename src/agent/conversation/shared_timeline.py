"""Single-user shared recent chat timeline."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.core.user_scope import CHAT_MEMORY_PLATFORMS, SINGLE_USER_ID
from src.memory.working import WorkingMemory

if TYPE_CHECKING:
    from src.infrastructure.model_gateway import ModelGateway
    from src.infrastructure.storage import MessageRepo


class SharedTimelineMemory:
    """Maintain one working-memory timeline shared across IM platforms."""

    def __init__(
        self,
        *,
        token_budget: int,
        include_platforms: tuple[str, ...] = tuple(CHAT_MEMORY_PLATFORMS),
    ) -> None:
        self._memory = WorkingMemory(
            conversation_id="shared-single-user-timeline",
            token_budget=token_budget,
        )
        self._include_platforms = tuple(include_platforms)
        self._loaded = False

    async def ensure_loaded(self, messages: MessageRepo) -> None:
        if self._loaded:
            return
        if not hasattr(messages, "get_recent_global"):
            self._loaded = True
            return
        recent = await messages.get_recent_global(
            self._memory._token_budget,  # noqa: SLF001
            self._include_platforms,
            user_id=SINGLE_USER_ID,
        )
        for item in recent:
            self._memory.add({"role": item["role"], "content": item["content"]})
        self._loaded = True

    def add(self, message: dict[str, Any]) -> None:
        self._memory.add(message)

    def get_messages(self) -> list[dict[str, Any]]:
        return self._memory.get_messages()

    def needs_compression(self) -> bool:
        return self._memory.needs_compression()

    def estimate_tokens(self) -> int:
        return self._memory.estimate_tokens()

    async def compress(self, model_gateway: ModelGateway) -> str:
        return await self._memory.compress(model_gateway)

    async def extract_before_compression(
        self,
        model_gateway: ModelGateway,
    ) -> list[dict[str, str]]:
        return await self._memory.extract_before_compression(model_gateway)
