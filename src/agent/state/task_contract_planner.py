"""LLM-assisted task contract planning."""

from __future__ import annotations

import json
from typing import Any

from src.agent.state.task_contract import (
    ACTION_ANSWER,
    ACTION_DIAGNOSE,
    ACTION_FILE_WRITE,
    ACTION_SCHEDULE_CREATE,
    ACTION_SCHEDULE_DELETE,
    ACTION_SCHEDULE_LIST,
    ACTION_SCHEDULE_UPDATE,
    TaskContract,
    TaskRequirement,
    build_task_contract,
)
from src.agent.state.task_contract_constraints import (
    filter_model_file_constraints,
    without_schedule_requirements,
)
from src.agent.state.task_contract_prompt import PLANNER_SYSTEM_PROMPT
from src.core.logging import get_logger

logger = get_logger(__name__)

_MIN_CONFIDENCE = 0.55
_MAX_CONTEXT_MESSAGES = 8
_MAX_MESSAGE_CHARS = 1200
_ALLOWED_ACTIONS = {
    ACTION_ANSWER,
    ACTION_DIAGNOSE,
    ACTION_FILE_WRITE,
    ACTION_SCHEDULE_CREATE,
    ACTION_SCHEDULE_DELETE,
    ACTION_SCHEDULE_LIST,
    ACTION_SCHEDULE_UPDATE,
}
_ACTION_ALIASES = {
    "answer": ACTION_ANSWER,
    "diagnose": ACTION_DIAGNOSE,
    "file_write": ACTION_FILE_WRITE,
    "file.write": ACTION_FILE_WRITE,
    "schedule_create": ACTION_SCHEDULE_CREATE,
    "schedule.create": ACTION_SCHEDULE_CREATE,
    "schedule_delete": ACTION_SCHEDULE_DELETE,
    "schedule.delete": ACTION_SCHEDULE_DELETE,
    "schedule_list": ACTION_SCHEDULE_LIST,
    "schedule.list": ACTION_SCHEDULE_LIST,
    "schedule_update": ACTION_SCHEDULE_UPDATE,
    "schedule.update": ACTION_SCHEDULE_UPDATE,
}


async def plan_scheduled_task_contract(
    model_gateway: Any,
    user_input: str,
    *,
    messages: list[dict[str, Any]],
    task_state: Any,
) -> TaskContract:
    contract = await plan_task_contract(
        model_gateway, user_input, messages=messages, task_state=task_state
    )
    return without_schedule_requirements(contract)


async def plan_task_contract(
    model_gateway: Any,
    user_input: str,
    *,
    messages: list[dict[str, Any]],
    task_state: Any,
) -> TaskContract:
    """Infer a task contract with model judgment, preserving deterministic facts."""
    baseline = build_task_contract(user_input)
    chat = getattr(model_gateway, "chat", None)
    if not callable(chat):
        return baseline
    planner_messages = _planner_messages(user_input, messages, task_state)
    try:
        response = await chat(
            planner_messages,
            tools=None,
            route_tier="simple",
            route_reason="task_contract",
            purpose="task_contract",
        )
    except Exception as exc:
        logger.warning("task_contract_planner.failed", error=str(exc))
        return baseline
    planned = _contract_from_text(
        str(getattr(response, "text", "")),
        baseline,
        planner_messages[-1]["content"],
    )
    if planned is None:
        logger.warning("task_contract_planner.parse_failed")
        return baseline
    _log_planned_contract(planned)
    return planned


def _planner_messages(
    user_input: str,
    messages: list[dict[str, Any]],
    task_state: Any,
) -> list[dict[str, str]]:
    context = _conversation_excerpt(messages)
    state_text = _task_state_text(task_state)
    user_payload = (
        f"Current user message:\n{user_input.strip()}\n\n"
        f"Recent conversation:\n{context or '(none)'}\n\n"
        f"Task state:\n{state_text or '(none)'}"
    )
    return [
        {"role": "system", "content": PLANNER_SYSTEM_PROMPT},
        {"role": "user", "content": user_payload},
    ]


def _contract_from_text(
    text: str,
    baseline: TaskContract,
    constraint_evidence: str,
) -> TaskContract | None:
    payload = _json_object(text)
    if payload is None:
        return None
    if _confidence(payload.get("confidence")) < _MIN_CONFIDENCE:
        return baseline
    model_requirements = tuple(
        filter_model_file_constraints(requirement, constraint_evidence)
        for requirement in _requirements_from_payload(payload)
    )
    return _merge_contracts(baseline, model_requirements)


def _requirements_from_payload(payload: dict[str, Any]) -> list[TaskRequirement]:
    raw_actions = payload.get("required_actions")
    if not isinstance(raw_actions, list):
        return []
    requirements: list[TaskRequirement] = []
    for raw_action in raw_actions:
        requirement = _requirement_from_raw_action(raw_action)
        if requirement is not None:
            requirements.append(requirement)
    return requirements


def _requirement_from_raw_action(value: Any) -> TaskRequirement | None:
    if isinstance(value, str):
        action = _normalize_action(value)
        return TaskRequirement(action) if action else None
    if not isinstance(value, dict):
        return None
    action = _normalize_action(str(value.get("action") or ""))
    if not action:
        return None
    return TaskRequirement(
        action,
        target_type=_target_type(action, value),
        target=str(value.get("target") or ""),
        target_paths=_string_tuple(value.get("target_paths")),
        allowed_write_dirs=_string_tuple(value.get("allowed_write_dirs")),
    )


def _merge_contracts(
    baseline: TaskContract,
    model_requirements: tuple[TaskRequirement, ...],
) -> TaskContract:
    requirements = list(baseline.required_actions)
    for requirement in model_requirements:
        if requirement.action == ACTION_ANSWER:
            continue
        existing_index = _requirement_index(requirements, requirement.action)
        if existing_index is None:
            requirements.append(requirement)
        else:
            requirements[existing_index] = _merge_requirement(
                requirements[existing_index],
                requirement,
            )
    return TaskContract(baseline.objective, tuple(requirements))


def _merge_requirement(
    baseline: TaskRequirement,
    model_requirement: TaskRequirement,
) -> TaskRequirement:
    return TaskRequirement(
        baseline.action,
        target_type=model_requirement.target_type or baseline.target_type,
        target=model_requirement.target or baseline.target,
        target_paths=_unique_strings(baseline.target_paths, model_requirement.target_paths),
        allowed_write_dirs=_unique_strings(
            baseline.allowed_write_dirs,
            model_requirement.allowed_write_dirs,
        ),
        resources=baseline.resources or model_requirement.resources,
    )


def _json_object(text: str) -> dict[str, Any] | None:
    start = text.find("{")
    if start < 0:
        return None
    try:
        value, _ = json.JSONDecoder().raw_decode(text[start:])
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def _conversation_excerpt(messages: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for message in messages[-_MAX_CONTEXT_MESSAGES:]:
        role = str(message.get("role") or "")
        if role not in {"user", "assistant"}:
            continue
        content = _message_text(message.get("content"))
        if content:
            lines.append(f"{role}: {_clip(content)}")
    return "\n".join(lines)


def _task_state_text(task_state: Any) -> str:
    protected_context = getattr(task_state, "protected_context", None)
    if not callable(protected_context):
        return ""
    return _clip(str(protected_context()))


def _message_text(content: Any) -> str:
    if isinstance(content, str):
        return " ".join(content.strip().split())
    if isinstance(content, list):
        parts = [item.get("text") for item in content if isinstance(item, dict)]
        return " ".join(str(part).strip() for part in parts if part)
    return ""


def _clip(text: str) -> str:
    return text[:_MAX_MESSAGE_CHARS]


def _confidence(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 1.0


def _normalize_action(value: str) -> str:
    normalized = value.strip().lower()
    action = _ACTION_ALIASES.get(normalized, normalized)
    return action if action in _ALLOWED_ACTIONS else ""


def _target_type(action: str, value: dict[str, Any]) -> str:
    explicit_type = str(value.get("target_type") or "")
    if explicit_type:
        return explicit_type
    if action == ACTION_FILE_WRITE:
        return "file"
    if action.startswith("schedule."):
        return "schedule"
    return ""


def _string_tuple(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        items = [value]
    elif isinstance(value, list):
        items = [item for item in value if isinstance(item, str)]
    else:
        items = []
    return tuple(dict.fromkeys(item.strip() for item in items if item.strip()))


def _unique_strings(first: tuple[str, ...], second: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys((*first, *second)))


def _requirement_index(requirements: list[TaskRequirement], action: str) -> int | None:
    for index, requirement in enumerate(requirements):
        if requirement.action == action:
            return index
    return None


def _log_planned_contract(contract: TaskContract) -> None:
    logger.info(
        "task_contract_planned",
        actions=[requirement.action for requirement in contract.required_actions],
    )
