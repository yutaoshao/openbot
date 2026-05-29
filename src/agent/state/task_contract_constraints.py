"""Trust boundaries for model-planned task constraints."""

from __future__ import annotations

from src.agent.state.task_contract import (
    ACTION_FILE_WRITE,
    ACTION_SCHEDULE_CREATE,
    ACTION_SCHEDULE_DELETE,
    ACTION_SCHEDULE_LIST,
    ACTION_SCHEDULE_UPDATE,
    TaskContract,
    TaskRequirement,
)

_SCHEDULE_ACTIONS = {
    ACTION_SCHEDULE_CREATE,
    ACTION_SCHEDULE_DELETE,
    ACTION_SCHEDULE_LIST,
    ACTION_SCHEDULE_UPDATE,
}


def filter_model_file_constraints(
    requirement: TaskRequirement,
    evidence_text: str,
) -> TaskRequirement:
    if requirement.action != ACTION_FILE_WRITE:
        return requirement
    return TaskRequirement(
        requirement.action,
        target_type=requirement.target_type,
        target=requirement.target,
        target_paths=_explicit_items(requirement.target_paths, evidence_text),
        allowed_write_dirs=_explicit_items(requirement.allowed_write_dirs, evidence_text),
    )


def _explicit_items(items: tuple[str, ...], evidence_text: str) -> tuple[str, ...]:
    return tuple(item for item in items if _appears_in_evidence(item, evidence_text))


def _appears_in_evidence(item: str, evidence_text: str) -> bool:
    trimmed = item.rstrip("/")
    return item in evidence_text or bool(trimmed and trimmed in evidence_text)


def without_schedule_requirements(contract: TaskContract) -> TaskContract:
    requirements = tuple(
        requirement
        for requirement in contract.required_actions
        if requirement.action not in _SCHEDULE_ACTIONS
    )
    return TaskContract(contract.objective, requirements)
