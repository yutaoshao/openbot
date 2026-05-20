"""Lightweight task outcome contract inferred from user input."""

from __future__ import annotations

import re
from dataclasses import dataclass

OUTCOME_ANSWER = "answer"
OUTCOME_DIAGNOSIS = "diagnosis"
OUTCOME_FILE_WRITE = "file_write"
OUTCOME_VERIFICATION = "verification"

_FILE_WRITE_KEYWORDS = (
    "保存",
    "写入",
    "追加",
    "补上",
    "存到",
    "save",
    "write",
    "append",
)
_DIAGNOSIS_KEYWORDS = (
    "为什么",
    "原因",
    "排查",
    "问题",
    "debug",
    "investigate",
)
_VERIFICATION_KEYWORDS = (
    "测试",
    "验证",
    "跑一下",
    "test",
    "verify",
)
_PATH_PATTERN = re.compile(r"`([^`]+)`|([\w./~-]+\.[A-Za-z0-9_]+)")
_TEMPLATE_PATH_PATTERN = re.compile(r"(Y{2,4}|M{2}|D{2})")
_PATH_CONTEXT_CHARS = 80


@dataclass(frozen=True)
class TaskContract:
    """Expected user-visible outcomes for one turn."""

    objective: str
    outcomes: frozenset[str]
    target_paths: tuple[str, ...] = ()
    allowed_write_dirs: tuple[str, ...] = ()

    @property
    def requires_file_write(self) -> bool:
        return OUTCOME_FILE_WRITE in self.outcomes


def build_task_contract(user_input: str) -> TaskContract:
    """Infer broad expected outcomes without prescribing tool order."""
    cleaned = " ".join(user_input.strip().split())
    outcomes = {OUTCOME_ANSWER}
    lowered = cleaned.lower()
    if _contains_any(lowered, _FILE_WRITE_KEYWORDS):
        outcomes.add(OUTCOME_FILE_WRITE)
    if _contains_any(lowered, _DIAGNOSIS_KEYWORDS):
        outcomes.add(OUTCOME_DIAGNOSIS)
    if _contains_any(lowered, _VERIFICATION_KEYWORDS):
        outcomes.add(OUTCOME_VERIFICATION)
    return TaskContract(
        objective=cleaned,
        outcomes=frozenset(outcomes),
        **_extract_write_targets(cleaned),
    )


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword in text for keyword in keywords)


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
    lowered = text.lower()
    return _contains_any(lowered, _FILE_WRITE_KEYWORDS)


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
