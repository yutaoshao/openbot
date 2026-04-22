"""Shared helpers for episodic memory."""

from __future__ import annotations

import math
from typing import Any

TITLE_CONTEXT_MESSAGES = 6
SUMMARY_HEAD = 10
SUMMARY_TAIL = 20

TITLE_SYSTEM_PROMPT = (
    "You are a concise title generator. "
    "Given the opening messages of a conversation, produce a short title "
    "(less than 50 characters) that captures the main topic. "
    "Return ONLY the title text, with no quotes or extra punctuation."
)

SUMMARY_SYSTEM_PROMPT = (
    "You are a conversation summarizer. "
    "Given a conversation between a user and an assistant, write a 2-3 "
    "sentence summary covering the key topics discussed, decisions made, "
    "and outcomes reached. "
    "Return ONLY the summary text."
)


def format_messages_for_llm(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    formatted: list[dict[str, Any]] = []
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if content:
            formatted.append({"role": role, "content": content})
    return formatted


def render_transcript(messages: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if content:
            lines.append(f"{role}: {content}")
    return "\n".join(lines)


def truncate_for_summary(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    total = SUMMARY_HEAD + SUMMARY_TAIL
    if len(messages) <= total:
        return messages
    placeholder = {
        "role": "system",
        "content": f"[... {len(messages) - total} messages omitted ...]",
    }
    return [*messages[:SUMMARY_HEAD], placeholder, *messages[-SUMMARY_TAIL:]]


def normalize_embedding(embedding: list[float]) -> list[float]:
    if not embedding:
        return []
    norm = math.sqrt(sum(value * value for value in embedding))
    if norm == 0:
        return []
    return [value / norm for value in embedding]


def belongs_to_user(conversation: dict[str, Any], user_id: str) -> bool:
    conversation_user_id = conversation.get("user_id", "")
    return conversation_user_id in {"", user_id}
