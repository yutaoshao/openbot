"""Retry policy for missing required file writes."""

from __future__ import annotations

from typing import Any

from src.agent.verification.stop import ledger_from_tool_calls

FILE_WRITE_RETRY_PROMPT = (
    "The previous answer did not confirm the required file write. "
    "Use an available filesystem tool to write the requested file now, "
    "then reply with the saved path. Do not claim the file is saved without "
    "a successful write tool result."
)


def needs_file_write_retry(contract: Any, tool_calls: list[dict[str, Any]]) -> bool:
    """Return whether the model must keep working to satisfy a file write."""
    requirement = contract.requirement_for("file.write")
    if requirement is None:
        return False
    ledger = ledger_from_tool_calls(tool_calls)
    return not ledger.satisfies(requirement)


def append_file_write_retry(messages: list[dict[str, Any]], final_text: str) -> None:
    """Add a corrective instruction after a missing required write."""
    if final_text.strip():
        messages.append({"role": "assistant", "content": final_text})
    messages.append({"role": "user", "content": FILE_WRITE_RETRY_PROMPT})
