from __future__ import annotations

from src.agent.state.task_contract import build_task_contract
from src.agent.verification.stop import ledger_from_tool_calls, verify_stop


def test_stop_verifier_preserves_answer_with_successful_tool_evidence() -> None:
    contract = build_task_contract("看下日志为什么失败")
    ledger = ledger_from_tool_calls(
        [
            {
                "name": "file_manager",
                "is_error": False,
                "result_preview": "read log",
                "effects": [
                    {
                        "action": "file.read",
                        "status": "completed",
                        "effect": "file_read",
                        "target_type": "file",
                        "target": "data/logs/openbot.log",
                        "name": "file_manager",
                    }
                ],
            },
            {
                "name": "read_file",
                "is_error": True,
                "result_preview": "Unknown tool: read_file",
                "effects": [],
            },
        ],
    )

    decision = verify_stop(contract, "模型调用了不存在的顶层工具。", ledger)

    assert decision.allow
    assert "模型调用了不存在的顶层工具。" in decision.message
    assert "Unknown tool: read_file" in decision.message
    assert "本轮未完成" not in decision.message


def test_stop_verifier_blocks_tool_error_without_successful_evidence() -> None:
    contract = build_task_contract("看下日志为什么失败")
    ledger = ledger_from_tool_calls(
        [
            {
                "name": "read_file",
                "is_error": True,
                "result_preview": "Unknown tool: read_file",
                "effects": [],
            },
        ],
    )

    decision = verify_stop(contract, "模型调用了不存在的工具名。", ledger)

    assert not decision.allow
    assert "本轮未完成" in decision.message
    assert "Unknown tool: read_file" in decision.message


def test_stop_verifier_keeps_vague_reply_incomplete_despite_successful_tool() -> None:
    contract = build_task_contract("看下日志为什么失败")
    ledger = ledger_from_tool_calls(
        [
            {
                "name": "file_manager",
                "is_error": False,
                "result_preview": "read log",
                "effects": [
                    {
                        "action": "file.read",
                        "status": "completed",
                        "effect": "file_read",
                        "target_type": "file",
                        "target": "data/logs/openbot.log",
                        "name": "file_manager",
                    }
                ],
            },
            {
                "name": "read_file",
                "is_error": True,
                "result_preview": "Unknown tool: read_file",
                "effects": [],
            },
        ],
    )

    decision = verify_stop(contract, "done", ledger)

    assert not decision.allow
    assert "模型调用工具后没有生成有效最终回复" in decision.message
    assert "Unknown tool: read_file" not in decision.message
