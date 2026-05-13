"""Persist oversized tool outputs and return model-safe references."""

from __future__ import annotations

import re
from datetime import datetime, tzinfo
from pathlib import Path

from src.core.trace import current_trace
from src.tools.registry import ToolResult

TOOL_OUTPUT_OFFLOAD_THRESHOLD = 10_000
TOOL_OUTPUT_PREVIEW_CHARS = 1_000
DEFAULT_TOOL_OUTPUT_ROOT = Path("data/tool_outputs")
_SAFE_PART = re.compile(r"[^A-Za-z0-9_.-]+")


def offload_tool_output_if_needed(
    tool_result: ToolResult,
    *,
    tool_name: str,
    tool_call_id: str,
    root: Path = DEFAULT_TOOL_OUTPUT_ROOT,
    now: datetime | None = None,
) -> ToolResult:
    """Save large tool output to disk and return a compact reference result."""
    content = tool_result.content
    if len(content) <= TOOL_OUTPUT_OFFLOAD_THRESHOLD:
        return tool_result

    timestamp = _local_now(now)
    relative_path = _output_path(
        root,
        timestamp=timestamp,
        trace_id=_trace_id(),
        tool_name=tool_name,
        tool_call_id=tool_call_id,
    )
    relative_path.parent.mkdir(parents=True, exist_ok=True)
    relative_path.write_text(content, encoding="utf-8")

    line_count = _line_count(content)
    metadata = {
        **tool_result.metadata,
        "offloaded": True,
        "output_file": relative_path.as_posix(),
        "original_chars": len(content),
        "original_lines": line_count,
    }
    return ToolResult(
        content=_reference_text(relative_path, content, line_count),
        is_error=tool_result.is_error,
        metadata=metadata,
    )


def _reference_text(path: Path, content: str, line_count: int) -> str:
    preview = content[:TOOL_OUTPUT_PREVIEW_CHARS]
    return (
        "Tool output exceeded 10000 chars and was saved to "
        f"{path.as_posix()}.\n"
        f"Original output: {len(content)} chars, {line_count} lines.\n"
        "Use file_manager read_file with this path to inspect the full output.\n\n"
        f"Preview:\n{preview}"
    )


def _output_path(
    root: Path,
    *,
    timestamp: datetime,
    trace_id: str,
    tool_name: str,
    tool_call_id: str,
) -> Path:
    filename = "_".join(
        [
            timestamp.strftime("%H%M%S_%f"),
            _safe(trace_id or "trace"),
            _safe(tool_name),
            _safe(tool_call_id or "call"),
        ]
    )
    return root / f"{timestamp:%Y}" / f"{timestamp:%m}" / f"{timestamp:%d}" / f"{filename}.txt"


def _safe(value: str) -> str:
    cleaned = _SAFE_PART.sub("-", value).strip("-")
    return cleaned or "item"


def _line_count(content: str) -> int:
    if not content:
        return 0
    return content.count("\n") + (0 if content.endswith("\n") else 1)


def _trace_id() -> str:
    trace = current_trace()
    return trace.trace_id if trace else ""


def _local_now(now: datetime | None) -> datetime:
    value = now or datetime.now().astimezone()
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("tool output timestamp must be timezone-aware")
    return value.astimezone(_local_timezone(value))


def _local_timezone(value: datetime) -> tzinfo:
    return datetime.now(value.tzinfo).astimezone().tzinfo or value.tzinfo
