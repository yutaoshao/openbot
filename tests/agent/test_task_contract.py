from __future__ import annotations

import pytest

from src.agent.state.task_contract import ACTION_ANSWER, ACTION_FILE_WRITE, build_task_contract


@pytest.mark.parametrize(
    "message",
    (
        "保存到 data/notes.md",
        "把内容追加到 data/notes.md",
        "请写入 data/notes.md",
        "把这段加到 data/notes.md",
        "请把“怎么使用”保存到 data/notes.md",
        "请保存类别说明到 data/notes.md",
        "把未完成的笔记保存到 data/notes.md",
        "可以帮我把内容保存到 data/notes.md 吗？",
        "请保存到 notes.md",
        "能不能保存到 data/notes.md？",
        "能否帮我保存到 data/notes.md？",
        "请帮忙保存到 data/notes.md",
        "先检查内容，然后保存到 data/notes.md",
        "你刚才保存了吗？现在重新保存到 data/notes.md",
        "记得使用 append_file 保存到 data/notes.md",
    ),
)
def test_task_contract_requires_explicit_file_write_commands(message: str) -> None:
    assert build_task_contract(message).requires_file_write


@pytest.mark.parametrize(
    "message",
    (
        "你用的是什么工具保存进去的？",
        "你没有保存错误，AI 八股.md 指的就是data/AI 八股.md。",
        "请问你刚才保存了吗？",
        "请不要把内容保存到 data/notes.md",
        "你未写入这份文件。",
        "我想知道怎么保存这个文件？",
        "我想确认你把它保存在哪了？",
        "可以告诉我你用什么工具保存吗？",
        "请把内容不要保存到 data/notes.md",
        "把内容不保存到 data/notes.md",
    ),
)
def test_task_contract_treats_file_write_discussion_as_answer_only(message: str) -> None:
    contract = build_task_contract(message)

    assert tuple(item.action for item in contract.required_actions) == (ACTION_ANSWER,)
    assert contract.requirement_for(ACTION_FILE_WRITE) is None


@pytest.mark.parametrize(
    ("message", "target_path"),
    (
        ("把内容保存到 data/AI 八股.md", "data/AI 八股.md"),
        ("把内容保存到 data/八股.md", "data/八股.md"),
        ("把内容保存到 `data/AI 八股.md`", "data/AI 八股.md"),
    ),
)
def test_task_contract_extracts_unicode_write_target(message: str, target_path: str) -> None:
    requirement = build_task_contract(message).requirement_for(ACTION_FILE_WRITE)

    assert requirement is not None
    assert requirement.target_paths == (target_path,)
