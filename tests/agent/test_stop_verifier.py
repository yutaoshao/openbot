from __future__ import annotations

from src.agent.state.task_contract import build_task_contract
from src.agent.verification.stop import ToolEvent, ToolLedger, verify_stop


def test_stop_verifier_rejects_required_write_without_confirmed_write() -> None:
    contract = build_task_contract("把第八节保存到读书笔记里")
    ledger = ToolLedger(
        (
            ToolEvent(
                name="file_manager",
                operation="read_file",
                path="data/reading_notes/我不是潘金莲.md",
                status="completed",
                effect="read",
                summary="read existing notes",
            ),
        )
    )

    decision = verify_stop(
        contract,
        "已保存到读书笔记。",
        ledger,
    )

    assert not decision.allow
    assert "未确认写入成功" in decision.message


def test_stop_verifier_allows_analysis_after_read_only_tool_use() -> None:
    contract = build_task_contract("帮我分析为什么回复了一半")
    ledger = ToolLedger(
        (
            ToolEvent(
                name="file_manager",
                operation="read_file",
                path="data/logs/openbot.log",
                status="completed",
                effect="read",
                summary="read logs",
            ),
        )
    )

    decision = verify_stop(
        contract,
        "原因是工具调用后模型只输出了 done，兜底摘要又被用户可见地发送。",
        ledger,
    )

    assert decision.allow
