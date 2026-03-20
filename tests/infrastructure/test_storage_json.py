from __future__ import annotations

from datetime import UTC, datetime

from src.channels.types import Attachment, MessageContent
from src.infrastructure.storage import _json_dumps, _json_loads


def test_json_dumps_supports_runtime_objects() -> None:
    payload = {
        "content": MessageContent(
            text="hello",
            attachments=[Attachment(type="image", data=b"\xe4\xbd\xa0", filename="a.png")],
        ),
        "timestamp": datetime(2026, 3, 20, 0, 0, tzinfo=UTC),
    }

    raw = _json_dumps(payload)

    assert raw is not None
    decoded = _json_loads(raw)
    assert decoded["content"]["text"] == "hello"
    assert decoded["content"]["attachments"][0]["data"] == "你"
    assert decoded["timestamp"].startswith("2026-03-20T00:00:00+00:00")
