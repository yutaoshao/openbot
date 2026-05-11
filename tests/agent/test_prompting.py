from __future__ import annotations

from types import SimpleNamespace

from src.agent.runtime.prompting import build_system_prompt


def test_system_prompt_treats_message_timestamps_as_internal_metadata() -> None:
    agent = SimpleNamespace(
        config=SimpleNamespace(system_prompt="Custom prompt for {date}."),
        skill_registry=None,
    )

    prompt = build_system_prompt(agent, input_text="hello")

    assert "Custom prompt for" in prompt
    assert "[YYYY-MM-DD HH:MM]" in prompt
    assert "internal message timestamp metadata" in prompt
    assert "Do not copy" in prompt
