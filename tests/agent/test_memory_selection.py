from __future__ import annotations

import pytest

from src.agent.turn_outcome import FailedTurn
from src.memory.turn_selection import select_memory_batch


def _message(role: str, content: str, **fields: object) -> dict[str, object]:
    return {"role": role, "content": content, **fields}


def test_selector_stops_before_concurrent_trailing_user() -> None:
    messages = [
        _message("user", "first question"),
        _message("assistant", "first answer"),
        _message("user", "next question still running"),
    ]

    memory_batch = select_memory_batch(messages, cursor=0)

    assert [message["content"] for message in memory_batch.messages] == [
        "first question",
        "first answer",
    ]
    assert memory_batch.next_cursor == 2


def test_selector_excludes_failed_pair_and_keeps_later_completed_pair() -> None:
    failure_metadata = FailedTurn("failed", reason="stop_verification").message_metadata()
    messages = [
        _message("user", "failed request"),
        _message("assistant", "failed reply", metadata=failure_metadata),
        _message("user", "completed request"),
        _message("assistant", "completed reply"),
    ]

    memory_batch = select_memory_batch(messages, cursor=0)

    assert [message["content"] for message in memory_batch.messages] == [
        "completed request",
        "completed reply",
    ]
    assert memory_batch.next_cursor == 4


def test_selector_skips_interrupted_orphan_before_later_completed_pair() -> None:
    messages = [
        _message("user", "orphan from interrupted run"),
        _message("user", "later request"),
        _message("assistant", "later reply"),
    ]

    memory_batch = select_memory_batch(messages, cursor=0)

    assert [message["content"] for message in memory_batch.messages] == [
        "later request",
        "later reply",
    ]
    assert memory_batch.next_cursor == 3


def test_selector_rejects_malformed_failure_fact() -> None:
    messages = [
        _message("user", "request"),
        _message("assistant", "reply", metadata={"turn_failure": "invalid"}),
    ]

    with pytest.raises(TypeError, match="turn failure metadata"):
        select_memory_batch(messages, cursor=0)
