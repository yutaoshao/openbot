from __future__ import annotations

from src.agent.state.task_contract import build_task_contract
from src.agent.verification.stop import ledger_from_tool_calls, verify_stop


def test_stop_verifier_allows_recovered_tool_validation_error() -> None:
    contract = build_task_contract("帮我修改")
    ledger = ledger_from_tool_calls(
        [
            {
                "name": "bash",
                "is_error": True,
                "result_preview": "Invalid arguments for bash: 1 validation error(s)",
                "effects": [
                    {
                        "action": "bash.validate",
                        "status": "validation_error",
                        "effect": "none",
                        "name": "bash",
                    },
                ],
            },
            {
                "name": "bash",
                "is_error": False,
                "result_preview": "pytest passed",
                "effects": [
                    {
                        "action": "command.execute",
                        "status": "completed",
                        "effect": "command_executed",
                        "target_type": "cwd",
                        "target": "/Users/yutaoshao/Project/openbot",
                        "name": "bash",
                    },
                ],
            },
        ],
    )

    decision = verify_stop(contract, "已修改并验证。", ledger)

    assert decision.allow


def test_stop_verifier_allows_recovered_edit_file_error_on_same_file() -> None:
    contract = build_task_contract("帮我更新学习笔记")
    ledger = ledger_from_tool_calls(
        [
            {
                "name": "edit_file",
                "is_error": True,
                "result_preview": "old_text not found",
                "effects": [
                    {
                        "action": "file.edit",
                        "status": "error",
                        "effect": "none",
                        "target_type": "file",
                        "target": "data/workspace/leetcode/day1.md",
                        "name": "edit_file",
                    },
                ],
            },
            {
                "name": "edit_file",
                "is_error": False,
                "result_preview": "Edited data/workspace/leetcode/day1.md",
                "effects": [
                    {
                        "action": "file.edit",
                        "status": "completed",
                        "effect": "file_written",
                        "target_type": "file",
                        "target": "data/workspace/leetcode/day1.md",
                        "name": "edit_file",
                    },
                ],
            },
        ],
    )

    decision = verify_stop(contract, "已更新到学习笔记。", ledger)

    assert decision.allow


def test_stop_verifier_keeps_edit_file_error_when_retry_writes_other_file() -> None:
    contract = build_task_contract("帮我更新学习笔记")
    ledger = ledger_from_tool_calls(
        [
            {
                "name": "edit_file",
                "is_error": True,
                "result_preview": "old_text not found",
                "effects": [
                    {
                        "action": "file.edit",
                        "status": "error",
                        "effect": "none",
                        "target_type": "file",
                        "target": "data/workspace/leetcode/day1.md",
                        "name": "edit_file",
                    },
                ],
            },
            {
                "name": "edit_file",
                "is_error": False,
                "result_preview": "Edited data/workspace/leetcode/day2.md",
                "effects": [
                    {
                        "action": "file.edit",
                        "status": "completed",
                        "effect": "file_written",
                        "target_type": "file",
                        "target": "data/workspace/leetcode/day2.md",
                        "name": "edit_file",
                    },
                ],
            },
        ],
    )

    decision = verify_stop(contract, "已更新到学习笔记。", ledger)

    assert not decision.allow
    assert "old_text not found" in decision.message


def test_stop_verifier_discloses_non_blocking_tool_error_after_required_write() -> None:
    contract = build_task_contract(
        "查询资料，保存到 data/workspace/research/openbot-daily/YYYY-MM-DD-topic.md"
    )
    ledger = ledger_from_tool_calls(
        [
            {
                "name": "web_fetch",
                "is_error": True,
                "result_preview": "HTTP error: 403",
                "effects": [],
            },
            {
                "name": "file_manager",
                "is_error": False,
                "result_preview": "Written report",
                "effects": [
                    {
                        "action": "file.write",
                        "status": "completed",
                        "effect": "file_written",
                        "target_type": "file",
                        "target": "data/workspace/research/openbot-daily/2026-05-31-topic.md",
                        "name": "file_manager",
                    },
                ],
            },
        ],
    )

    decision = verify_stop(contract, "已保存到每日技术调研报告。", ledger)

    assert decision.allow
    assert "已保存到每日技术调研报告。" in decision.message
    assert "HTTP error: 403" in decision.message
    assert "本轮未完成" not in decision.message


def test_stop_verifier_blocks_tool_error_when_no_required_operation_completed() -> None:
    contract = build_task_contract("帮我排查为什么网页打不开")
    ledger = ledger_from_tool_calls(
        [
            {
                "name": "web_fetch",
                "is_error": True,
                "result_preview": "HTTP error: 403",
                "effects": [],
            },
        ],
    )

    decision = verify_stop(contract, "网页可能被限制访问。", ledger)

    assert not decision.allow
    assert "本轮未完成" in decision.message
    assert "HTTP error: 403" in decision.message
