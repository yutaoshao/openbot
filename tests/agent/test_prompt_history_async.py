"""Original history I/O must not stall the message event loop."""

from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.agent.conversation.prompt_builder import PromptBuilder


@pytest.mark.asyncio
async def test_history_read_runs_while_the_event_loop_can_serve_other_work() -> None:
    entered = threading.Event()
    release = threading.Event()

    class SlowHistory:
        def context(self, *args, **kwargs) -> str:
            entered.set()
            if not release.wait(timeout=2):
                raise TimeoutError("History read was not released")
            return "历史原话"

    builder = PromptBuilder(
        semantic_memory=SimpleNamespace(recall=AsyncMock(return_value=[])),
        episodic_memory=SimpleNamespace(recall=AsyncMock(return_value=[])),
        procedural_memory=SimpleNamespace(get_system_prompt_context=AsyncMock(return_value="")),
        personal_profile=SimpleNamespace(context=lambda *args, **kwargs: ""),
        personal_history=SlowHistory(),
    )
    operation = asyncio.create_task(builder.enrich("系统提示", "历史问题", "user"))
    try:
        assert await asyncio.to_thread(entered.wait, 1)
        await asyncio.wait_for(asyncio.sleep(0.01), timeout=0.2)
        assert not operation.done()
    finally:
        release.set()
    assert "历史原话" in await operation
