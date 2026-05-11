from __future__ import annotations

from datetime import UTC, datetime

import src.memory.message_format as message_format
from src.memory.message_format import render_llm_message


def test_render_assistant_message_does_not_duplicate_internal_timestamp(
    monkeypatch,
) -> None:
    monkeypatch.setattr(message_format, "_local_timezone", lambda: UTC)
    message = {
        "role": "assistant",
        "content": "[2026-05-11 11:50] 抱歉，你说过了。",
        "timestamp": datetime(2026, 5, 11, 11, 50, tzinfo=UTC),
    }

    rendered = render_llm_message(message)

    assert rendered["content"] == "[2026-05-11 11:50] 抱歉，你说过了。"


def test_render_assistant_message_collapses_repeated_internal_timestamps(
    monkeypatch,
) -> None:
    monkeypatch.setattr(message_format, "_local_timezone", lambda: UTC)
    message = {
        "role": "assistant",
        "content": "[2026-05-11 11:50] [2026-05-11 11:50] 抱歉，你说过了。",
        "timestamp": datetime(2026, 5, 11, 11, 50, tzinfo=UTC),
    }

    rendered = render_llm_message(message)

    assert rendered["content"] == "[2026-05-11 11:50] 抱歉，你说过了。"


def test_render_user_message_preserves_literal_timestamp_text(monkeypatch) -> None:
    monkeypatch.setattr(message_format, "_local_timezone", lambda: UTC)
    message = {
        "role": "user",
        "content": "[2026-05-11 11:49] 这就是我发的正文",
        "timestamp": datetime(2026, 5, 11, 11, 50, tzinfo=UTC),
    }

    rendered = render_llm_message(message)

    assert rendered["content"] == (
        "[2026-05-11 11:50] [2026-05-11 11:49] 这就是我发的正文"
    )
