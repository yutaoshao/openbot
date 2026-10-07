"""Count the complete model input, including message envelopes and tool schemas."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import tiktoken

from src.core.logging import get_logger

_ENCODING = tiktoken.get_encoding("o200k_base")
UNKNOWN_CONTEXT_LIMIT = 128_000
ESTIMATED_REQUEST_OVERHEAD = 4_096
logger = get_logger(__name__)


@dataclass(frozen=True)
class InputCount:
    tokens: int
    exact: bool
    model_window: int | None = None
    output_budget: int = 0


def estimate_input_tokens(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
) -> InputCount:
    """Conservative local count when the provider cannot count its request."""
    payload = json.dumps(messages, ensure_ascii=False, default=str, separators=(",", ":"))
    schemas = json.dumps(tools or [], ensure_ascii=False, default=str, separators=(",", ":"))
    tokens = len(_ENCODING.encode(payload)) + len(_ENCODING.encode(schemas))
    return InputCount(tokens=int(tokens * 1.15) + 32, exact=False)


def request_limit(input_budget: int, model_window: int | None, output_budget: int) -> int:
    if model_window is None:
        return min(input_budget, UNKNOWN_CONTEXT_LIMIT)
    available = model_window - output_budget
    if available <= 0:
        raise ValueError("Model context window must exceed max output tokens")
    return min(input_budget, available)


async def compact_request_history(
    messages: list[dict[str, Any]],
    model_gateway: Any,
    *,
    recent_budget: int,
) -> bool:
    """Summarize closed turns while keeping the current tool chain intact."""
    from src.memory.turn_selection import recent_turn_cut
    from src.memory.working_compaction import summarize_messages

    first_user = next(
        (i for i, message in enumerate(messages) if message.get("role") == "user"), -1
    )
    cut = recent_turn_cut(messages, recent_budget)
    if first_user < 0 or not cut:
        return False
    older = messages[first_user:cut]
    if not older:
        return False
    summary = await summarize_messages(model_gateway=model_gateway, messages=older)
    if not summary:
        logger.error(
            "request_history.compression_failed_preserving_original",
            message_count=len(older),
        )
        return False
    references = set()
    for message in older:
        match = re.search(r"^\[(\d{4}-\d\d-\d\d \d\d:\d\d)\]", str(message.get("content", "")))
        if match:
            try:
                day = datetime.fromisoformat(match[1])
            except ValueError:
                continue
            references.add(f"data/conversations/{day:%Y/%m/%d}.jsonl")
    if references:
        summary += "\n原始历史来源：" + "、".join(sorted(references))
    messages[first_user:cut] = [
        {"role": "system", "content": f"Summary of earlier conversation:\n{summary}"}
    ]
    return True
