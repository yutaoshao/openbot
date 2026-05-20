from __future__ import annotations

from src.agent.runtime.stream import _needs_file_write_retry
from src.agent.state.task_contract import build_task_contract
from src.agent.verification.stop import (
    ToolEvent,
    ToolLedger,
    ledger_from_tool_calls,
    verify_stop,
)

RESEARCH_PROMPT = """每天早上 3 点，针对 OpenBot 的一个具体功能点做一次技术调研。

执行步骤：
1. 读取 `data/workspace/research/openbot-daily/`，根据已有报告决定下一个功能点。
2. 使用 file_manager 保存到：
   `data/workspace/research/openbot-daily/YYYY-MM-DD-NN-topic-slug.md`
"""


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


def test_stop_verifier_allows_concrete_write_for_template_path() -> None:
    contract = build_task_contract("保存到文件 data/diaries/YYYY-MM-DD.md")
    ledger = ToolLedger(
        (
            ToolEvent(
                name="file_manager",
                operation="write_file",
                path="data/diaries/2026-05-10.md",
                status="completed",
                effect="written",
                summary="Written diary",
            ),
        )
    )

    decision = verify_stop(contract, "已保存到 data/diaries/2026-05-10.md。", ledger)

    assert decision.allow


def test_task_contract_treats_template_save_path_as_allowed_write_dir() -> None:
    contract = build_task_contract(RESEARCH_PROMPT)

    assert contract.requires_file_write
    assert contract.target_paths == ()
    assert contract.allowed_write_dirs == ("data/workspace/research/openbot-daily/",)


def test_stop_verifier_allows_write_inside_template_save_dir() -> None:
    contract = build_task_contract(RESEARCH_PROMPT)
    ledger = ToolLedger(
        (
            ToolEvent(
                name="file_manager",
                operation="write_file",
                path="data/workspace/research/openbot-daily/2026-05-20-01-topic.md",
                status="completed",
                effect="written",
                summary="Written report",
            ),
        )
    )

    decision = verify_stop(contract, "已保存到每日技术调研报告。", ledger)

    assert decision.allow


def test_stop_verifier_rejects_write_outside_template_save_dir() -> None:
    contract = build_task_contract(RESEARCH_PROMPT)
    ledger = ToolLedger(
        (
            ToolEvent(
                name="file_manager",
                operation="write_file",
                path="data/diaries/2026-05-20.md",
                status="completed",
                effect="written",
                summary="Written unrelated file",
            ),
        )
    )

    decision = verify_stop(contract, "已保存。", ledger)

    assert not decision.allow
    assert "未确认写入成功" in decision.message


def test_runtime_retry_accepts_write_inside_template_save_dir() -> None:
    contract = build_task_contract(RESEARCH_PROMPT)
    tool_calls = [
        {
            "name": "file_manager",
            "is_error": False,
            "result_preview": "Written report",
            "metadata": {
                "operation": "write_file",
                "path": "data/workspace/research/openbot-daily/2026-05-20-01-topic.md",
                "status": "completed",
                "effect": "written",
            },
        }
    ]

    assert not _needs_file_write_retry(contract, tool_calls)


def test_ledger_ignores_successful_tool_business_status() -> None:
    ledger = ledger_from_tool_calls(
        [
            {
                "name": "schedule_manager",
                "is_error": False,
                "result_preview": "Created schedule abc. Status: active.",
                "metadata": {"id": "abc", "status": "active"},
            },
        ]
    )

    assert not ledger.has_problem_events()


def test_ledger_preserves_failed_tool_status_detail() -> None:
    ledger = ledger_from_tool_calls(
        [
            {
                "name": "bash",
                "is_error": True,
                "result_preview": "Tool 'bash' timed out after 60.00s",
                "metadata": {"status": "timeout", "effect": "none"},
            },
        ]
    )

    assert ledger.events[0].status == "timeout"
    assert ledger.has_problem_events()
