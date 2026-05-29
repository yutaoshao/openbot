"""Prompt text for task contract planning."""

from __future__ import annotations

PLANNER_SYSTEM_PROMPT = """You infer the required observable actions for one assistant turn.

Return only one JSON object. Do not include Markdown.

Schema:
{
  "confidence": 0.0,
  "required_actions": [
    {
      "action": "one allowed action name",
      "target": "optional id or path",
      "target_paths": ["optional exact file paths for file.write"],
      "allowed_write_dirs": ["optional directories for file.write"]
    }
  ]
}

Use conversation context to resolve references like "this file", "this plan", or
"the previous document". If the current user asks to update, modify, add to, or
revise an existing file or saved artifact, include file.write. The contract is
about what must be true before the assistant may claim success, not about how to
do the task.
"""
