"""Trust boundaries for model-planned task constraints."""

from __future__ import annotations

from src.agent.state.file_write_intent import FileWriteIntent
from src.agent.state.task_contract import (
    ACTION_FILE_WRITE,
    ACTION_SCHEDULE_CREATE,
    ACTION_SCHEDULE_DELETE,
    ACTION_SCHEDULE_LIST,
    ACTION_SCHEDULE_UPDATE,
    TaskContract,
    TaskRequirement,
    classify_file_write_intent,
)

_SCHEDULE_ACTIONS = {
    ACTION_SCHEDULE_CREATE,
    ACTION_SCHEDULE_DELETE,
    ACTION_SCHEDULE_LIST,
    ACTION_SCHEDULE_UPDATE,
}
_PATH_EXTENSION_CHARACTERS = frozenset("._/~\\-")
_ROOT_PATHS = frozenset({".", "./"})
_ROOT_LEFT_DELIMITERS = frozenset("`'\"([{<:：")
_ROOT_RIGHT_DELIMITERS = frozenset("`'\")]}>:：,，;；!！?？")
_PATH_INTRODUCER_SUFFIXES = (
    "保存",
    "保存到",
    "写入",
    "追加",
    "追加到",
    "补上",
    "存到",
    "加到",
    "文件",
    "路径",
    "目录",
    "save",
    "write",
    "append",
    "to",
    "as",
)


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


def trusted_model_requirements(
    requirements: tuple[TaskRequirement, ...],
    user_input: str,
) -> tuple[TaskRequirement, ...]:
    """Reject model-added writes when the current message only discusses writing."""
    if classify_file_write_intent(user_input) is not FileWriteIntent.DISCUSSION:
        return requirements
    return tuple(
        requirement for requirement in requirements if requirement.action != ACTION_FILE_WRITE
    )


def _explicit_items(items: tuple[str, ...], evidence_text: str) -> tuple[str, ...]:
    return tuple(item for item in items if _appears_in_evidence(item, evidence_text))


def _appears_in_evidence(item: str, evidence_text: str) -> bool:
    candidate = item.strip()
    if not candidate:
        return False
    if candidate in _ROOT_PATHS:
        return _root_path_appears(candidate, evidence_text)
    variants = tuple(dict.fromkeys((candidate, candidate.rstrip("/"))))
    return any(variant and _has_complete_path_token(variant, evidence_text) for variant in variants)


def _root_path_appears(candidate: str, evidence_text: str) -> bool:
    variants = ("./", ".") if candidate == "." else ("./",)
    return any(_has_standalone_root_token(variant, evidence_text) for variant in variants)


def _has_standalone_root_token(candidate: str, evidence_text: str) -> bool:
    start = 0
    while (index := evidence_text.find(candidate, start)) >= 0:
        end = index + len(candidate)
        left = evidence_text[index - 1] if index else ""
        right = evidence_text[end] if end < len(evidence_text) else ""
        if _root_left_boundary(left) and _root_right_boundary(right, candidate):
            return True
        start = index + 1
    return False


def _root_left_boundary(character: str) -> bool:
    return not character or character.isspace() or character in _ROOT_LEFT_DELIMITERS


def _root_right_boundary(character: str, candidate: str) -> bool:
    if candidate == "./" and character and not _extends_root_path(character):
        return True
    return not character or character.isspace() or character in _ROOT_RIGHT_DELIMITERS


def _has_complete_path_token(candidate: str, evidence_text: str) -> bool:
    start = 0
    while (index := evidence_text.find(candidate, start)) >= 0:
        end = index + len(candidate)
        left = evidence_text[index - 1] if index else ""
        right = evidence_text[end] if end < len(evidence_text) else ""
        if (
            _has_candidate_left_boundary(
                candidate,
                evidence_text,
                index,
                left_character=left,
            )
            and not _extends_candidate_path(right, candidate[-1])
            and not _continues_preceding_path(evidence_text, index)
        ):
            return True
        start = index + 1
    return False


def _continues_preceding_path(evidence_text: str, index: int) -> bool:
    if index == 0 or evidence_text[index - 1] not in {" ", "\t"}:
        return False
    preceding_text = evidence_text[:index].rstrip()
    if not preceding_text:
        return False
    preceding_token = preceding_text.split()[-1]
    if _preceded_by_path_introducer(evidence_text, index):
        return False
    return any(character.isalnum() for character in preceding_token)


def _has_candidate_left_boundary(
    candidate: str,
    evidence_text: str,
    index: int,
    *,
    left_character: str,
) -> bool:
    return not _extends_candidate_path(
        left_character,
        candidate[0],
    ) or _preceded_by_path_introducer(evidence_text, index)


def _preceded_by_path_introducer(evidence_text: str, index: int) -> bool:
    preceding_text = evidence_text[:index].rstrip().lower()
    return preceding_text.endswith(_PATH_INTRODUCER_SUFFIXES)


def _extends_root_path(character: str) -> bool:
    return bool(character) and (character.isalnum() or character in _PATH_EXTENSION_CHARACTERS)


def _extends_candidate_path(character: str, candidate_edge: str) -> bool:
    return bool(character) and (
        character.isascii()
        and character.isalnum()
        or character in _PATH_EXTENSION_CHARACTERS
        or character.isalnum()
        and not candidate_edge.isascii()
    )


def without_schedule_requirements(contract: TaskContract) -> TaskContract:
    requirements = tuple(
        requirement
        for requirement in contract.required_actions
        if requirement.action not in _SCHEDULE_ACTIONS
    )
    return TaskContract(contract.objective, requirements)
