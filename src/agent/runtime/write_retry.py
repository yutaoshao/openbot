"""Retry policy for missing required file writes."""

from __future__ import annotations

from typing import Any

from src.agent.state.task_contract import ACTION_FILE_WRITE
from src.agent.verification.stop import ledger_from_tool_calls
from src.core.logging import get_logger

logger = get_logger(__name__)

FILE_WRITE_RETRY_PROMPT = (
    "The previous answer did not confirm the required file write. "
    "Use an available filesystem tool to write the requested file now, "
    "then reply with the saved path. Do not claim the file is saved without "
    "a successful write tool result."
)


def needs_file_write_retry(contract: Any, tool_calls: list[dict[str, Any]]) -> bool:
    """Return whether the model must keep working to satisfy a file write."""
    requirement = contract.requirement_for(ACTION_FILE_WRITE)
    if requirement is None:
        return False
    ledger = ledger_from_tool_calls(tool_calls)
    if ledger.satisfies(requirement):
        return False
    logger.info(
        "file_write_retry_required",
        expected_targets=list(requirement.target_paths),
        expected_dirs=list(requirement.allowed_write_dirs),
        observed_targets=list(_observed_write_targets(ledger.events)),
        resource_errors=[
            resource.to_dict() for resource in requirement.resources if resource.error
        ],
    )
    return True


def append_file_write_retry(messages: list[dict[str, Any]], final_text: str) -> None:
    """Add a corrective instruction after a missing required write."""
    if final_text.strip():
        messages.append({"role": "assistant", "content": final_text})
    messages.append({"role": "user", "content": FILE_WRITE_RETRY_PROMPT})


def _observed_write_targets(events: tuple[Any, ...]) -> tuple[str, ...]:
    targets: list[str] = []
    for event in events:
        if event.action not in {ACTION_FILE_WRITE, "file.edit"}:
            continue
        if event.effect != "file_written":
            continue
        target = event.resource.canonical if event.resource else event.target
        if target:
            targets.append(target)
    return tuple(dict.fromkeys(targets))
