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
        recent_budget: int | None = None,
        include_platforms: tuple[str, ...] = tuple(CHAT_MEMORY_PLATFORMS),
    ) -> None:
        self._memory = WorkingMemory(
            conversation_id="shared-single-user-timeline",
            token_budget=token_budget,
            recent_budget=recent_budget,
        )
        self._include_platforms = tuple(include_platforms)
        self._recent_budget = recent_budget or token_budget
        self._loaded = False
        self._repository: MessageRepo | None = None

    async def ensure_loaded(
        self, messages: MessageRepo, model_gateway: ModelGateway | None = None
    ) -> None:
        if self._loaded:
            return
        if not hasattr(messages, "get_recent_global"):
            self._loaded = True
            return
        self._repository = messages
        summary = (await messages.get_working_summary()
                   if hasattr(messages, "get_working_summary") else None)
        if summary:
            recent = await messages.get_global_after(
                summary["boundary_id"], self._include_platforms, user_id=SINGLE_USER_ID
            )
            self._memory._summary = summary["content"]
        else:
            recent = (await messages.get_global_history(
                self._include_platforms, user_id=SINGLE_USER_ID
            ) if model_gateway is not None and hasattr(messages, "get_global_history")
                else await messages.get_recent_global(
                    self._recent_budget, self._include_platforms, user_id=SINGLE_USER_ID
                ))
        for index, item in enumerate(recent, 1):
            timeline_message = {
                "role": item["role"],
                "content": item["content"],
                "timestamp": item["timestamp"],
            }
            if item.get("id"):
                timeline_message["id"] = item["id"]
            if item.get("metadata") is not None:
                timeline_message["metadata"] = item["metadata"]
            self._memory.add(timeline_message)
            if (model_gateway is not None and index % 32 == 0
                    and self._memory.needs_compression()):
                await self.compress(model_gateway)
        if model_gateway is not None and self.estimate_tokens() > self._recent_budget:
            await self.compress(model_gateway)
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
        async def persist(summary: str, boundary: dict) -> None:
            if self._repository is not None and hasattr(self._repository, "save_working_summary"):
                if not boundary.get("id"):
                    raise ValueError("Cannot persist compression without a source message ID")
                await self._repository.save_working_summary(boundary["id"], summary)

        return await self._memory.compress(model_gateway, persist=persist)

    async def extract_before_compression(
        self,
        model_gateway: ModelGateway,
    ) -> list[dict[str, str]]:
        return await self._memory.extract_before_compression(model_gateway)
