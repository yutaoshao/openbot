"""Resolve task contract targets to canonical resource identities."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from src.agent.state.task_contract import ACTION_FILE_WRITE, TaskContract, TaskRequirement
from src.core.logging import get_logger
from src.tools.builtin.path_utils import resolve_file_resource

if TYPE_CHECKING:
    from src.tools.effects import ResourceRef

logger = get_logger(__name__)


def resolve_agent_contract_resources(contract: TaskContract, agent: Any) -> TaskContract:
    """Resolve resources with the project root used by registered file tools."""
    resolved = resolve_contract_resources(contract, _agent_project_root(agent))
    _log_resolved_contract(resolved)
    return resolved


def resolve_contract_resources(contract: TaskContract, root: Path | None) -> TaskContract:
    """Return a contract whose resource targets are canonicalized at the boundary."""
    return TaskContract(
        objective=contract.objective,
        required_actions=tuple(
            _resolve_requirement(requirement, root) for requirement in contract.required_actions
        ),
    )


def _resolve_requirement(requirement: TaskRequirement, root: Path | None) -> TaskRequirement:
    if requirement.action != ACTION_FILE_WRITE:
        return requirement
    resources = tuple(
        resolve_file_resource(root, path) for path in requirement.target_paths
    )
    directory_resources = tuple(
        resolve_file_resource(root, directory) for directory in requirement.allowed_write_dirs
    )
    return TaskRequirement(
        action=requirement.action,
        target_type=requirement.target_type,
        target=requirement.target,
        target_paths=tuple(_canonical_targets(resources, requirement.target_paths)),
        allowed_write_dirs=tuple(
            _canonical_dirs(directory_resources, requirement.allowed_write_dirs)
        ),
        resources=resources + directory_resources,
    )


def _agent_project_root(agent: Any) -> Path | None:
    registry = getattr(agent, "tool_registry", None)
    if registry is None:
        return None
    for tool in registry.list_all():
        project_root = getattr(tool, "project_root", None)
        if isinstance(project_root, Path):
            return project_root
        root = getattr(tool, "_root", None)
        if isinstance(root, Path):
            return root.resolve()
    return None


def _log_resolved_contract(contract: TaskContract) -> None:
    logger.info(
        "task_contract_resources_resolved",
        actions=[requirement.action for requirement in contract.required_actions],
        resources=[
            resource.to_dict()
            for requirement in contract.required_actions
            for resource in requirement.resources
        ],
    )


def _canonical_targets(
    resources: tuple[ResourceRef, ...],
    raw_targets: tuple[str, ...],
) -> tuple[str, ...]:
    if not resources:
        return raw_targets
    return tuple(resource.canonical for resource in resources if resource.canonical)


def _canonical_dirs(
    resources: tuple[ResourceRef, ...],
    raw_dirs: tuple[str, ...],
) -> tuple[str, ...]:
    if not resources:
        return raw_dirs
    return tuple(
        _with_trailing_slash(resource.canonical)
        for resource in resources
        if resource.canonical
    )


def _with_trailing_slash(path: str) -> str:
    return path if path.endswith("/") else f"{path}/"
