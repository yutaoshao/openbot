"""A saved summary boundary and complete turns must survive restart together."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from src.agent.conversation.shared_timeline import SharedTimelineMemory
from src.infrastructure.model_gateway import ModelResponse


class Messages:
    def __init__(self) -> None:
        start = datetime(2026, 9, 27, tzinfo=UTC)
        self.items = [
            {
                "id": f"m{index}",
                "role": "user" if index % 2 == 0 else "assistant",
                "content": f"message {index}",
                "timestamp": start + timedelta(seconds=index),
            }
            for index in range(6)
        ]
        self.summary: dict[str, str] | None = None
        self.fail_save = True

    async def get_working_summary(self):
        return self.summary

    async def get_recent_global(self, budget, platforms, *, user_id):
        return self.items

    async def get_global_after(self, boundary_id, platforms, *, user_id):
        boundary = next(index for index, row in enumerate(self.items) if row["id"] == boundary_id)
        return self.items[boundary + 1 :]

    async def save_working_summary(self, boundary_id, content):
        if self.fail_save:
            raise OSError("summary write failed")
        self.summary = {"boundary_id": boundary_id, "content": content}


class Gateway:
    async def chat(self, messages):
        return ModelResponse(text="summary of first complete turn")


async def test_failed_summary_write_preserves_raw_history_then_restart_restores_pairs() -> None:
    repository = Messages()
    timeline = SharedTimelineMemory(token_budget=1, recent_budget=170)
    await timeline.ensure_loaded(repository)
    before = timeline.get_messages()

    with pytest.raises(OSError, match="summary write failed"):
        await timeline.compress(Gateway())
    assert timeline.get_messages() == before
    assert repository.summary is None

    repository.fail_save = False
    await timeline.compress(Gateway())
    assert repository.summary is not None
    restarted = SharedTimelineMemory(token_budget=1, recent_budget=170)
    await restarted.ensure_loaded(repository)

    assert restarted.get_messages() == timeline.get_messages()
    assert repository.summary["boundary_id"] == "m3"
    assert [item["role"] for item in restarted.get_messages()] == [
        "system",
        "user",
        "assistant",
    ]
