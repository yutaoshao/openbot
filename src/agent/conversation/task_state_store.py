"""Conversation-scoped task state and protected context store."""

from __future__ import annotations

import time
from collections import OrderedDict

from src.agent.state import TaskState


class TaskStateStore:
    """Maintain task state and protected context per conversation."""

    def __init__(self) -> None:
        self._states: dict[str, TaskState] = {}
        self._protected: dict[str, OrderedDict[str, str]] = {}
        self._last_active: dict[str, float] = {}

    def ensure(self, conversation_id: str) -> TaskState:
        state = self._states.setdefault(conversation_id, TaskState())
        self._protected.setdefault(conversation_id, OrderedDict())
        self._touch(conversation_id)
        self._sync_task_state(conversation_id)
        return state

    def get(self, conversation_id: str) -> TaskState | None:
        return self._states.get(conversation_id)

    def note_user_input(self, conversation_id: str, content: str) -> None:
        self.ensure(conversation_id).note_user_input(content)
        self._sync_task_state(conversation_id)

    def note_assistant_reply(self, conversation_id: str, content: str) -> None:
        self.ensure(conversation_id).note_assistant_reply(content)
        self._sync_task_state(conversation_id)

    def record_tool_event(
        self,
        conversation_id: str,
        tool_name: str,
        summary: str,
        *,
        is_error: bool,
        activated_tools: list[str] | None = None,
    ) -> None:
        self.ensure(conversation_id).record_tool_event(
            tool_name,
            summary,
            is_error=is_error,
            activated_tools=activated_tools,
        )
        self._sync_task_state(conversation_id)

    def set_protected(self, conversation_id: str, key: str, content: str) -> None:
        if not key:
            return
        cleaned = content.strip()
        protected = self._protected.setdefault(conversation_id, OrderedDict())
        if not cleaned:
            protected.pop(key, None)
            return
        protected[key] = cleaned
        protected.move_to_end(key)
        self._touch(conversation_id)

    def get_protected_messages(self, conversation_id: str) -> list[dict[str, str]]:
        protected = self._protected.get(conversation_id, OrderedDict())
        return [
            {
                "role": "system",
                "content": f"Protected Context ({key}):\n{content}",
            }
            for key, content in protected.items()
            if content
        ]

    def stale_conversations(self, ttl_seconds: float, *, now: float | None = None) -> list[str]:
        current = time.monotonic() if now is None else now
        return [
            conversation_id
            for conversation_id, last_active in self._last_active.items()
            if current - last_active > ttl_seconds
        ]

    def clear(self, conversation_id: str) -> None:
        self._states.pop(conversation_id, None)
        self._protected.pop(conversation_id, None)
        self._last_active.pop(conversation_id, None)

    def _sync_task_state(self, conversation_id: str) -> None:
        state = self._states.get(conversation_id)
        if state is None:
            return
        self.set_protected(
            conversation_id,
            "task_state",
            state.protected_context(),
        )

    def _touch(self, conversation_id: str) -> None:
        self._last_active[conversation_id] = time.monotonic()
