"""Shared helpers for storage repositories."""

from __future__ import annotations

import contextlib
import json
import uuid
from dataclasses import asdict, is_dataclass
from datetime import UTC, datetime
from typing import Any

CHARS_PER_TOKEN = 4


def now_utc() -> str:
    return datetime.now(UTC).isoformat()


def new_id() -> str:
    return uuid.uuid4().hex


def json_dumps(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False, default=_json_default)


def json_loads(raw: str | None) -> Any:
    if raw is None:
        return None
    return json.loads(raw)


def row_to_dict(
    row: Any,
    columns: list[str],
    json_fields: set[str] | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for idx, col in enumerate(columns):
        value = row[idx]
        if json_fields and col in json_fields and isinstance(value, str):
            value = json_loads(value)
        result[col] = value
    return result


def _json_default(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")

    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        with contextlib.suppress(Exception):
            return model_dump()

    return str(value)
