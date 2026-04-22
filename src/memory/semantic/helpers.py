"""Shared constants and pure helpers for semantic memory."""

from __future__ import annotations

import json
import math
from datetime import UTC, datetime, timedelta
from typing import Any

from src.core.logging import get_logger

logger = get_logger(__name__)

PRIORITY_TTL: dict[str, timedelta | None] = {
    "P0": None,
    "P1": timedelta(days=90),
    "P2": timedelta(days=30),
}
VALID_CATEGORIES = {"fact", "concept", "procedure", "reference"}
VALID_PRIORITIES = {"P0", "P1", "P2"}
DUPLICATE_THRESHOLD = 0.85

EXTRACTION_PROMPT = """\
You are a knowledge extraction engine. Analyze the conversation below and \
extract persistent, actionable knowledge items.

Rules:
- Extract ONLY facts, concepts, procedures, or references worth remembering.
- Skip greetings, filler, transient context, and small talk.
- Each item must be self-contained and useful without the original conversation.
- Assign a priority:
  P0 = critical/permanent facts (identity, core preferences, key decisions)
  P1 = useful information (technical details, project context, how-tos)
  P2 = minor details (casual mentions, low-impact notes)

Return a JSON array. Each element:
{
  "category": "fact" | "concept" | "procedure" | "reference",
  "content": "<concise knowledge statement>",
  "tags": ["tag1", "tag2"],
  "priority": "P0" | "P1" | "P2"
}

If nothing worth extracting, return an empty array: []

Conversation:
"""


def calculate_expires_at(priority: str) -> str | None:
    ttl = PRIORITY_TTL.get(priority)
    if ttl is None:
        return None
    return (datetime.now(UTC) + ttl).isoformat()


def normalize_embedding(embedding: list[float]) -> list[float]:
    if not embedding:
        return []
    norm = math.sqrt(sum(value * value for value in embedding))
    if norm == 0:
        return []
    return [value / norm for value in embedding]


def l2_distance_to_cosine_similarity(distance: float) -> float:
    similarity = 1.0 - ((distance * distance) / 2.0)
    return max(-1.0, min(1.0, similarity))


def format_messages(messages: list[dict]) -> str:
    lines: list[str] = []
    for msg in messages:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        lines.append(f"{role}: {content}")
    return "\n".join(lines)


def parse_extraction_response(text: str) -> list[dict[str, Any]]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        first_newline = cleaned.find("\n")
        if first_newline != -1:
            cleaned = cleaned[first_newline + 1:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3].rstrip()

    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        logger.warning("semantic.parse_extraction_failed", response_len=len(text))
        return []

    if not isinstance(parsed, list):
        return []
    return [item for item in parsed if isinstance(item, dict)]


def belongs_to_user(entry: dict[str, Any], user_id: str) -> bool:
    entry_user_id = entry.get("user_id", "")
    return entry_user_id in {"", user_id}
