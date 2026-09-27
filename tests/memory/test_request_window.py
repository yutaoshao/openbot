import time
from types import SimpleNamespace

import pytest

from src.agent.runtime.turn_loop import TurnLoopExecution
from src.core.config import AgentConfig, ModelProviderConfig
from src.memory.request_budget import InputCount, request_limit


def test_window_limit_and_invalid_reservation():
    assert request_limit(272_000, 272_000, 16_384) == 255_616
    assert request_limit(255_616, None, 16_384) == 128_000
    with pytest.raises(ValueError, match="context_window must exceed"):
        ModelProviderConfig(context_window=16_384, max_tokens=16_384)


@pytest.mark.parametrize("exact", [False, True])
async def test_compression_uses_effective_input_budget_not_counting_capability(monkeypatch, exact):
    state = {"tokens": 200_000, "compressions": 0}

    class Gateway:
        async def count_input(self, *args, **kwargs):
            return InputCount(state["tokens"], exact, 272_000, 16_384)

    async def compact(messages, gateway, *, recent_budget):
        assert recent_budget == 128_000
        state["compressions"] += 1
        state["tokens"] = 128_000
        return True

    monkeypatch.setattr("src.agent.runtime.turn_loop.compact_request_history", compact)
    context = SimpleNamespace(
        agent=SimpleNamespace(config=AgentConfig(), model_gateway=Gateway()),
        route_decision=None,
        clock=time.monotonic,
        messages=[{"role": "user", "content": "question"}],
    )
    loop = TurnLoopExecution(context)
    await loop._prepare_request_budget(None)
    assert state["compressions"] == 0
    state["tokens"] = 230_055
    await loop._prepare_request_budget([{"name": "large_tool"}])
    assert state["compressions"] == 1
