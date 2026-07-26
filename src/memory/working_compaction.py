"""LLM adapter for working-memory summary and knowledge extraction."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.core.logging import get_logger
from src.memory.message_format import render_llm_message
from src.memory.structured_json import parse_json_array_response

if TYPE_CHECKING:
    from src.infrastructure.model_gateway import ModelGateway

logger = get_logger(__name__)

_COMPRESS_PROMPT = """\
Summarise the following conversation messages concisely.
Preserve:
- Key decisions and action items
- Important facts and conclusions
- Entity names, technical terms, and specific values
- User preferences and constraints

Discard greetings, filler, and redundant exchanges.
Return ONLY the summary text, nothing else.

Messages:
{messages}
"""

_EXTRACT_PROMPT = """\
Analyse the following conversation messages and extract important \
knowledge items that should be remembered long-term.

For each item, classify it into exactly one category:
- fact      : concrete information, data points, stated truths
- concept   : ideas, explanations, mental models
- procedure : how-to steps, workflows, user preferences on process

Filter out noise (greetings, filler, acknowledgements).

Return ONLY a raw JSON array of objects with keys "category" and "content".
Example:
[
  {{"category": "fact", "content": "User's timezone is Asia/Shanghai"}},
  {{"category": "procedure", "content": "Deploy via 'make release' then tag"}}
]

Do not include markdown fences, explanations, or tool calls.
If nothing worth extracting, return an empty array: []

Messages:
{messages}
"""


async def summarize_messages(
    *,
    model_gateway: ModelGateway,
    messages: list[dict[str, Any]],
) -> str:
    """Return a provider-generated summary for eligible messages."""
    prompt = _COMPRESS_PROMPT.format(messages=_format_messages(messages))
    response = await model_gateway.chat(
        messages=[{"role": "user", "content": prompt}],
    )
    return response.text.strip()


async def extract_memory_items(
    *,
    model_gateway: ModelGateway,
    messages: list[dict[str, Any]],
    conversation_id: str,
) -> list[dict[str, str]]:
    """Extract validated fact, concept, and procedure items."""
    logger.info(
        "working_memory.extract.start",
        conversation_id=conversation_id,
        message_count=len(messages),
    )
    prompt = _EXTRACT_PROMPT.format(messages=_format_messages(messages))
    response = await model_gateway.chat(
        messages=[{"role": "user", "content": prompt}],
    )
    parsed_items = parse_json_array_response(response.text)
    if not parsed_items.ok:
        logger.warning(
            "working_memory.extract.parse_failed",
            conversation_id=conversation_id,
            raw_length=len(response.text.strip()),
            reason=parsed_items.reason,
        )
        return []
    valid_items = _valid_memory_items(parsed_items.items)
    logger.info(
        "working_memory.extract.done",
        conversation_id=conversation_id,
        extracted=len(valid_items),
        discarded=len(parsed_items.items) - len(valid_items),
    )
    return valid_items


def _format_messages(messages: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for message in messages:
        role = message.get("role", "unknown")
        content = render_llm_message(message).get("content", "")
        parts.append(f"[{role}] {content}")
    return "\n".join(parts)


def _valid_memory_items(items: list[Any]) -> list[dict[str, str]]:
    allowed_categories = {"fact", "concept", "procedure"}
    return [
        {"category": item["category"], "content": item["content"]}
        for item in items
        if isinstance(item, dict)
        and isinstance(item.get("category"), str)
        and isinstance(item.get("content"), str)
        and item["category"] in allowed_categories
    ]
