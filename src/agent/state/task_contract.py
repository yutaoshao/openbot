"""Structured task outcome contract inferred from user input."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from src.agent.state.file_write_intent import (
    FileWriteIntent,
    classify_trusted_file_write_intent,
    contains_file_write_action,
)

if TYPE_CHECKING:
    from src.tools.effects import ResourceRef

ACTION_ANSWER = "answer"
ACTION_DIAGNOSE = "diagnose"
ACTION_FILE_WRITE = "file.write"
ACTION_SCHEDULE_CREATE = "schedule.create"
ACTION_SCHEDULE_DELETE = "schedule.delete"
ACTION_SCHEDULE_LIST = "schedule.list"
ACTION_SCHEDULE_UPDATE = "schedule.update"

_DIAGNOSIS_KEYWORDS = ("为什么", "原因", "排查", "问题", "debug", "investigate")
_SCHEDULE_WORDS = ("定时任务", "schedule", "scheduled task")
_SCHEDULE_CREATE_WORDS = ("创建", "新增", "新建", "添加", "create", "add")
_SCHEDULE_UPDATE_WORDS = ("修改", "更新", "改成", "改为", "update", "change")
_SCHEDULE_DELETE_WORDS = ("删除", "移除", "取消", "delete", "remove", "cancel")
_SCHEDULE_LIST_WORDS = ("列出", "查看", "有哪些", "list", "show")
_PAYLOAD_MARKERS = ("改成：", "改为：", "更新为：", "改成:", "改为:", "更新为:")
_QUESTION_MARKERS = ("?", "？", "是不是", "是否", "要不要", "需不需要", "需要哪些", "怎么")
_PATH_PATTERN = re.compile(
    r"`([^`\n]+)`|((?:[A-Za-z0-9_.~-]+/)+"
    r"[^`\n，。！？；;:'\"<>|]*\.[A-Za-z0-9_]+|[A-Za-z0-9_./~-]+\.[A-Za-z0-9_]+)"
)
_CODE_FENCE_PATTERN = re.compile(r"```.*?```", re.DOTALL)
_QUOTE_BLOCK_PATTERN = re.compile(r"(?m)^>.*$")
_SCHEDULE_ID_PATTERN = re.compile(r"(?:定时任务\s+|schedule\s+)([A-Za-z0-9_-]+)")
_CLAUSE_SPLIT_PATTERN = re.compile(r"[。！？?；;\n]")
_LIST_ITEM_PATTERN = re.compile(r"^\s*(?:[-*+]|\d+[.)、])\s+")
_TEMPLATE_PATH_PATTERN = re.compile(r"(Y{2,4}|M{2}|D{2})")
_EXAMPLE_MARKERS = ("例如", "比如", "for example", "examples")
_PATH_CONTEXT_CHARS = 80


@dataclass(frozen=True)
class TaskRequirement:
    """One required action for the current turn."""

    action: str
    target_type: str = ""
    target: str = ""
    target_paths: tuple[str, ...] = ()
    allowed_write_dirs: tuple[str, ...] = ()
    resources: tuple[ResourceRef, ...] = ()


@dataclass(frozen=True)
class TaskContract:
    """Expected user-visible outcomes for one turn."""

    objective: str
    required_actions: tuple[TaskRequirement, ...]

    @property
    def outcomes(self) -> frozenset[str]:
        """Backward-compatible set of required action names."""
        return frozenset(requirement.action for requirement in self.required_actions)

    @property
    def requires_file_write(self) -> bool:
        return self.requirement_for(ACTION_FILE_WRITE) is not None

    @property
    def target_paths(self) -> tuple[str, ...]:
        requirement = self.requirement_for(ACTION_FILE_WRITE)
        return requirement.target_paths if requirement else ()

    @property
    def allowed_write_dirs(self) -> tuple[str, ...]:
        requirement = self.requirement_for(ACTION_FILE_WRITE)
        return requirement.allowed_write_dirs if requirement else ()

    def requirement_for(self, action: str) -> TaskRequirement | None:
        for requirement in self.required_actions:
            if requirement.action == action:
                return requirement
        return None


def build_task_contract(user_input: str) -> TaskContract:
    """Infer broad expected actions without prescribing tool order."""
    cleaned = " ".join(user_input.strip().split())
    trusted_text = _strip_example_list_blocks(_strip_untrusted_blocks(user_input))
    parse_text = _command_before_payload(trusted_text)
    requirements = [TaskRequirement(ACTION_ANSWER)]
    schedule_requirement = _schedule_requirement(trusted_text)
    if schedule_requirement is not None:
        requirements.append(schedule_requirement)
    elif classify_trusted_file_write_intent(parse_text) is FileWriteIntent.COMMAND:
        requirements.append(_file_write_requirement(parse_text))
    if _contains_any(parse_text.lower(), _DIAGNOSIS_KEYWORDS):
        requirements.append(TaskRequirement(ACTION_DIAGNOSE))
    return TaskContract(objective=cleaned, required_actions=tuple(requirements))


def _strip_untrusted_blocks(text: str) -> str:
    without_code = _CODE_FENCE_PATTERN.sub(" ", text)
    return _QUOTE_BLOCK_PATTERN.sub(" ", without_code)


def _strip_example_list_blocks(text: str) -> str:
    lines: list[str] = []
    skipping_examples = False
    for line in text.splitlines():
        stripped = line.strip()
        if skipping_examples:
            if _is_list_item(stripped):
                continue
            skipping_examples = False
        lines.append(line)
        if _contains_any(stripped.lower(), _EXAMPLE_MARKERS):
            skipping_examples = True
    return "\n".join(lines)


def _is_list_item(line: str) -> bool:
    return bool(_LIST_ITEM_PATTERN.match(line))


def _command_before_payload(text: str) -> str:
    cut = min(
        (index for marker in _PAYLOAD_MARKERS if (index := text.find(marker)) >= 0),
        default=-1,
    )
    if cut < 0:
        return text
    return text[:cut]


def _schedule_requirement(text: str) -> TaskRequirement | None:
    schedule_clauses = tuple(_schedule_clauses(text))
    if not schedule_clauses:
        return None
    schedule_id = _schedule_id(text)
    command_clauses = tuple(clause for clause in schedule_clauses if not _is_question(clause))
    if _clauses_contain(command_clauses, _SCHEDULE_UPDATE_WORDS):
        return TaskRequirement(ACTION_SCHEDULE_UPDATE, "schedule", schedule_id)
    if _clauses_contain(command_clauses, _SCHEDULE_DELETE_WORDS):
        return TaskRequirement(ACTION_SCHEDULE_DELETE, "schedule", schedule_id)
    if _clauses_contain(schedule_clauses, _SCHEDULE_LIST_WORDS):
        return TaskRequirement(ACTION_SCHEDULE_LIST, "schedule", schedule_id)
    if _clauses_contain(command_clauses, _SCHEDULE_CREATE_WORDS):
        return TaskRequirement(ACTION_SCHEDULE_CREATE, "schedule", schedule_id)
    return None


def _schedule_clauses(text: str) -> list[str]:
    clauses: list[str] = []
    for sentence in _CLAUSE_SPLIT_PATTERN.split(text):
        parts = [part.strip() for part in re.split(r"[,，]", sentence) if part.strip()]
        clauses.extend(part for part in parts if _contains_any(part.lower(), _SCHEDULE_WORDS))
    return clauses


def _is_question(clause: str) -> bool:
    return _contains_any(clause.lower(), _QUESTION_MARKERS)


def _clauses_contain(clauses: tuple[str, ...], keywords: tuple[str, ...]) -> bool:
    return any(_contains_any(clause.lower(), keywords) for clause in clauses)


def classify_file_write_intent(user_input: str) -> FileWriteIntent:
    """Classify explicit write commands and explicit write-only discussion."""
    trusted_text = _strip_example_list_blocks(_strip_untrusted_blocks(user_input))
    return classify_trusted_file_write_intent(_command_before_payload(trusted_text))


def _file_write_requirement(text: str) -> TaskRequirement:
    targets = _extract_write_targets(text)
    return TaskRequirement(ACTION_FILE_WRITE, "file", "", **targets)


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword in text for keyword in keywords)


def _schedule_id(text: str) -> str:
    match = _SCHEDULE_ID_PATTERN.search(text)
    return match.group(1) if match else ""


def _extract_write_targets(text: str) -> dict[str, tuple[str, ...]]:
    paths: list[str] = []
    dirs: list[str] = []
    for match in _PATH_PATTERN.finditer(text):
        path = (match.group(1) or match.group(2) or "").strip()
        context = text[max(0, match.start() - _PATH_CONTEXT_CHARS) : match.start()]
        if not path or not _is_write_context(context):
            continue
        if _is_template_path(path):
            dirs.append(_template_parent_dir(path))
        elif _is_directory_path(path):
            dirs.append(_normal_dir(path))
        else:
            paths.append(path)
    return {
        "target_paths": tuple(dict.fromkeys(paths)),
        "allowed_write_dirs": tuple(dict.fromkeys(item for item in dirs if item)),
    }


def _is_write_context(text: str) -> bool:
    return contains_file_write_action(text)


def _is_template_path(path: str) -> bool:
    return bool(_TEMPLATE_PATH_PATTERN.search(path))


def _template_parent_dir(path: str) -> str:
    match = _TEMPLATE_PATH_PATTERN.search(path)
    if match is None:
        return ""
    prefix = path[: match.start()]
    slash = prefix.rfind("/")
    if slash < 0:
        return ""
    return _normal_dir(prefix[: slash + 1])


def _is_directory_path(path: str) -> bool:
    return path.endswith("/")


def _normal_dir(path: str) -> str:
    cleaned = path.strip()
    return cleaned if cleaned.endswith("/") else f"{cleaned}/"
