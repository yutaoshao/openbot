import pytest

from src.agent.state.task_contract import ACTION_FILE_WRITE, TaskRequirement
from src.agent.state.task_contract_constraints import filter_model_file_constraints


def test_model_constraints_require_complete_path_evidence() -> None:
    requirement = TaskRequirement(
        ACTION_FILE_WRITE,
        target_paths=("data/AI 八股.md", "八股.md", "data/第二份.md"),
        allowed_write_dirs=(".",),
    )

    filtered = filter_model_file_constraints(
        requirement,
        "待写入文件：\ndata/AI 八股.md\ndata/第二份.md",
    )

    assert filtered.target_paths == ("data/AI 八股.md", "data/第二份.md")
    assert filtered.allowed_write_dirs == ()


def test_model_constraints_accept_explicit_project_root_evidence() -> None:
    requirement = TaskRequirement(ACTION_FILE_WRITE, allowed_write_dirs=(".",))

    filtered = filter_model_file_constraints(
        requirement,
        "把生成的文件写入项目根目录 `.`。",
    )

    assert filtered.allowed_write_dirs == (".",)


@pytest.mark.parametrize(
    ("candidate", "evidence"),
    (
        ("八股.md", "请写入算法八股.md"),
        ("八股.md", "请写入 AI 八股.md"),
        ("AI 八股.md", "请写入data/AI 八股.md"),
    ),
)
def test_model_constraints_reject_filename_suffix_guesses(
    candidate: str,
    evidence: str,
) -> None:
    requirement = TaskRequirement(ACTION_FILE_WRITE, target_paths=(candidate,))

    filtered = filter_model_file_constraints(requirement, evidence)

    assert filtered.target_paths == ()


@pytest.mark.parametrize(
    "evidence",
    (
        "请写入data/AI 八股.md",
        "请写入 data/AI 八股.md",
        "待写入文件：\ndata/AI 八股.md",
    ),
)
def test_model_constraints_accept_complete_unicode_path(evidence: str) -> None:
    requirement = TaskRequirement(
        ACTION_FILE_WRITE,
        target_paths=("data/AI 八股.md",),
    )

    filtered = filter_model_file_constraints(requirement, evidence)

    assert filtered.target_paths == ("data/AI 八股.md",)


def test_model_constraints_accept_complete_chinese_basename_after_action() -> None:
    requirement = TaskRequirement(ACTION_FILE_WRITE, target_paths=("八股.md",))

    filtered = filter_model_file_constraints(requirement, "请写入八股.md")

    assert filtered.target_paths == ("八股.md",)
