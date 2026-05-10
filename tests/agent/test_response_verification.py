from __future__ import annotations

from src.agent.state import TaskState
from src.agent.verification import verify_final_response


def test_vague_post_tool_reply_exposes_incomplete_turn() -> None:
    task_state = TaskState(objective="保存第二章第八节到读书笔记")
    task_state.record_tool_event(
        "file_manager",
        "read_file data/reading_notes/我不是潘金莲.md",
        is_error=False,
    )

    content, rewritten = verify_final_response(
        "done",
        tool_calls_made=[{"name": "file_manager"}],
        task_state=task_state,
    )

    assert rewritten is True
    assert "本轮未完成" in content
    assert "Objective:" not in content
    assert "Evidence:" not in content


def test_short_meaningful_reply_is_not_rewritten_as_incomplete() -> None:
    task_state = TaskState(objective="保存第二章第八节到读书笔记")
    task_state.record_tool_event(
        "file_manager",
        "write_file data/reading_notes/我不是潘金莲.md",
        is_error=False,
    )

    content, rewritten = verify_final_response(
        "已保存。",
        tool_calls_made=[{"name": "file_manager"}],
        task_state=task_state,
    )

    assert rewritten is False
    assert content == "已保存。"
