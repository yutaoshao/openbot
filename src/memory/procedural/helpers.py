"""Shared prompt/parsing helpers for procedural memory."""

from __future__ import annotations

import json
from typing import Any

from src.core.logging import get_logger

logger = get_logger(__name__)

CATEGORIES: frozenset[str] = frozenset(
    {"communication", "coding", "workflow", "tool"}
)

OBSERVATION_PROMPT = """\
You are a preference extraction engine.  Analyze the conversation below and
extract any user preferences you can identify.

Look for:
1. **Explicit statements** - "I prefer Python", "always use type hints",
   "reply in Chinese" (confidence: 0.9)
2. **Corrections** - the user correcting the assistant implies a preference
   (confidence: 0.6)
3. **Repeated patterns** - the user consistently requesting a certain format
   or style (confidence: 0.4)

Categorize each preference into exactly one of:
- communication: language preference, response length, formality, tone
- coding: preferred languages, frameworks, style conventions
- workflow: preferred tools, processes, habits
- tool: tool-specific preferences and configurations

Return a JSON array (no markdown fences).  Each element must have:
- "category": one of communication / coding / workflow / tool
- "key": short snake_case identifier (e.g. "preferred_language")
- "value": concise description of the preference
- "confidence": float (0.9 / 0.6 / 0.4 per the rules above)

Only extract **clear** preferences.  Skip anything ambiguous.
If no preferences are found, return an empty array: []

Conversation:
"""


def format_messages(messages: list[dict[str, Any]]) -> str:
    return "\n".join(
        f"[{msg.get('role', 'unknown')}]: {msg.get('content', '')}"
        for msg in messages
    )


def parse_preferences(text: str) -> list[dict[str, Any]]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        first_newline = cleaned.index("\n") + 1
        cleaned = cleaned[first_newline:]
    if cleaned.endswith("```"):
        cleaned = cleaned[: cleaned.rfind("```")]
    cleaned = cleaned.strip()

    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        logger.warning("procedural.parse_failed", text_preview=cleaned[:200])
        return []

    if not isinstance(parsed, list):
        return []
    return [item for item in parsed if isinstance(item, dict)]


def dedupe_preferences(prefs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: dict[tuple[str, str], dict[str, Any]] = {}
    for pref in prefs:
        token = (pref["category"], pref["key"])
        current = deduped.get(token)
        if current is None or not current.get("user_id"):
            deduped[token] = pref
    return list(deduped.values())
