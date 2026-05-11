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


@dataclass(frozen=True)
class TaskContract:
    """Expected user-visible outcomes for one turn."""

    objective: str
    outcomes: frozenset[str]
    target_paths: tuple[str, ...] = ()

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
        target_paths=_extract_target_paths(cleaned),
    )


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword in text for keyword in keywords)


def _extract_target_paths(text: str) -> tuple[str, ...]:
    paths = []
    for match in _PATH_PATTERN.finditer(text):
        path = (match.group(1) or match.group(2) or "").strip()
        if path and not _is_template_path(path):
            paths.append(path)
    return tuple(dict.fromkeys(paths))


def _is_template_path(path: str) -> bool:
    return bool(_TEMPLATE_PATH_PATTERN.search(path))
