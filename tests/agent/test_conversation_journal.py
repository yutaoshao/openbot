from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta, timezone

from src.agent.conversation.journal import ConversationJournal, ConversationJournalEntry


def test_conversation_journal_writes_messages_by_local_event_date(tmp_path) -> None:
    journal = ConversationJournal(root=tmp_path, local_tz=timezone(timedelta(hours=8)))
    entry = ConversationJournalEntry(
        ts=datetime(2026, 5, 10, 16, 30, tzinfo=UTC),
        role="user",
        content="你好",
        channel="feishu",
        conversation_id="conv-1",
        message_id="platform-msg-1",
        user_id="openbot-local-user",
        platform_user_id="sender-1",
    )

    path = journal.append(entry)

    assert path == tmp_path / "2026" / "05" / "11.jsonl"
    raw = path.read_text(encoding="utf-8")
    assert "你好" in raw
    data = json.loads(raw)
    assert data["ts"] == "2026-05-11T00:30:00+08:00"
    assert data["role"] == "user"
    assert data["channel"] == "feishu"
    assert data["conversation_id"] == "conv-1"
    assert data["message_id"] == "platform-msg-1"
    assert data["user_id"] == "openbot-local-user"
    assert data["platform_user_id"] == "sender-1"


def test_conversation_journal_keeps_assistant_trace_and_usage_fields(tmp_path) -> None:
    journal = ConversationJournal(root=tmp_path, local_tz=UTC)
    entry = ConversationJournalEntry(
        ts=datetime(2026, 5, 10, 14, 30, 5, tzinfo=UTC),
        role="assistant",
        content="你好！",
        channel="wechat",
        conversation_id="conv-2",
        message_id="stored-msg-2",
        model="fake-model",
        trace_id="trace-123",
        tokens_in=12,
        tokens_out=8,
        latency_ms=34,
        tool_calls=[{"name": "web_fetch", "is_error": False}],
    )

    path = journal.append(entry)

    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["ts"] == "2026-05-10T14:30:05+00:00"
    assert data["role"] == "assistant"
    assert data["model"] == "fake-model"
    assert data["trace_id"] == "trace-123"
    assert data["tokens_in"] == 12
    assert data["tokens_out"] == 8
    assert data["latency_ms"] == 34
    assert data["tool_calls"] == [{"name": "web_fetch", "is_error": False}]
