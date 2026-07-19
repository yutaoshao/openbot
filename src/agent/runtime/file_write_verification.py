"""Required file-mutation verification at the model boundary."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.agent.state.task_contract import ACTION_FILE_WRITE
from src.agent.verification.stop import ledger_from_tool_calls
from src.agent.verification.stop_messages import missing_requirement_message
from src.core.logging import get_logger
from src.tools.file_mutation_receipt import FILE_MUTATION_ACTIONS

if TYPE_CHECKING:
    from pathlib import Path

logger = get_logger(__name__)


def file_write_verification_failure(
    contract: Any,
    tool_calls: list[dict[str, Any]],
    *,
    project_root: Path | None = None,
) -> str | None:
    """Return an explicit failure when a required mutation lacks a valid receipt."""
    requirement = contract.requirement_for(ACTION_FILE_WRITE)
    if requirement is None:
        return None
    ledger = ledger_from_tool_calls(tool_calls)
    if ledger.satisfies(requirement, project_root=project_root):
        return None
    logger.warning(
        "file_write_verification_failed",
        expected_targets=list(requirement.target_paths),
        expected_dirs=list(requirement.allowed_write_dirs),
        observed_targets=list(_observed_write_targets(ledger.events)),
        resource_errors=[
            resource.to_dict() for resource in requirement.resources if resource.error
        ],
    )
    return missing_requirement_message(requirement, {}, ledger.events)


def _observed_write_targets(events: tuple[Any, ...]) -> tuple[str, ...]:
    targets: list[str] = []
    for event in events:
        if event.action not in FILE_MUTATION_ACTIONS:
            continue
        if event.effect != "file_written":
            continue
        target = event.resource.canonical if event.resource else event.target
        if target:
            targets.append(target)
    return tuple(dict.fromkeys(targets))
