from __future__ import annotations

from src.agent.runtime.stream import _needs_file_write_retry
from src.agent.state.task_contract import (
    ACTION_FILE_WRITE,
    ACTION_SCHEDULE_UPDATE,
    build_task_contract,
)
from src.agent.verification.stop import (
    ToolLedger,
    ledger_from_tool_calls,
    verify_stop,
)
from src.tools.effects import ToolEffect

RESEARCH_PROMPT = """每天早上 3 点，针对 OpenBot 的一个具体功能点做一次技术调研。

执行步骤：
1. 读取 `data/workspace/research/openbot-daily/`，根据已有报告决定下一个功能点。
2. 使用 file_manager 保存到：
   `data/workspace/research/openbot-daily/YYYY-MM-DD-NN-topic-slug.md`
"""


def _actions(contract) -> dict[str, object]:
    return {requirement.action: requirement for requirement in contract.required_actions}


def test_stop_verifier_rejects_required_write_without_confirmed_write() -> None:
    contract = build_task_contract("把第八节保存到读书笔记里")
    ledger = ToolLedger(
        (
            ToolEffect(
                action="file.read",
                effect="file_read",
                name="file_manager",
                status="completed",
                target_type="file",
                target="data/reading_notes/我不是潘金莲.md",
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
            ToolEffect(
                action="file.read",
                effect="file_read",
                name="file_manager",
                status="completed",
                target_type="file",
                target="data/logs/openbot.log",
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
    contract = build_task_contract("保存到文件 data/diaries/YYYY/MM/YYYY-MM-DD.md")
    ledger = ToolLedger(
        (
            ToolEffect(
                action="file.write",
                effect="file_written",
                name="file_manager",
                status="completed",
                target_type="file",
                target="data/diaries/2026/05/2026-05-10.md",
                summary="Written diary",
            ),
        )
    )

    decision = verify_stop(contract, "已保存到 data/diaries/2026/05/2026-05-10.md。", ledger)

    assert decision.allow


def test_task_contract_treats_template_save_path_as_allowed_write_dir() -> None:
    contract = build_task_contract(RESEARCH_PROMPT)
    file_requirement = _actions(contract)[ACTION_FILE_WRITE]

    assert contract.requires_file_write
    assert file_requirement.target_paths == ()
    assert file_requirement.allowed_write_dirs == ("data/workspace/research/openbot-daily/",)


def test_task_contract_ignores_chinese_date_format_as_exact_path() -> None:
    contract = build_task_contract(
        "我想保存下来类似日报，保存格式也是/年/月/日.md。今天早上看了一眼小林 coding。"
    )
    file_requirement = _actions(contract)[ACTION_FILE_WRITE]

    assert contract.requires_file_write
    assert file_requirement.target_paths == ()
    assert file_requirement.allowed_write_dirs == ()


def test_stop_verifier_allows_actual_write_for_chinese_date_format() -> None:
    contract = build_task_contract(
        "我想保存下来类似日报，保存格式也是/年/月/日.md。今天早上看了一眼小林 coding。"
    )
    ledger = ToolLedger(
        (
            ToolEffect(
                action="file.write",
                effect="file_written",
                name="file_manager",
                status="completed",
                target_type="file",
                target="data/workspace/daily/2026/05/2026-05-28.md",
                summary="Written daily report",
            ),
        )
    )

    decision = verify_stop(
        contract,
        "已保存到 data/workspace/daily/2026/05/2026-05-28.md。",
        ledger,
    )

    assert decision.allow


def test_task_contract_treats_schedule_prompt_as_payload_not_file_write() -> None:
    contract = build_task_contract(
        """把定时任务 sched-1 的描述改成：
每天早上 3 点，针对 OpenBot 的一个具体功能点做一次技术调研。

执行步骤：
1. 读取 `data/workspace/research/openbot-daily/`，根据已有报告决定下一个功能点。
2. 使用 file_manager 保存到：
   `data/workspace/research/openbot-daily/YYYY-MM-DD-NN-topic-slug.md`
"""
    )
    actions = _actions(contract)

    assert ACTION_SCHEDULE_UPDATE in actions
    assert ACTION_FILE_WRITE not in actions
    assert actions[ACTION_SCHEDULE_UPDATE].target == "sched-1"


def test_task_contract_treats_code_block_as_payload_not_file_write() -> None:
    contract = build_task_contract(
        """解释这段代码，不要修改文件：

```python
path = "data/workspace/research/openbot-daily/YYYY-MM-DD.md"
print("保存到", path)
```
"""
    )

    assert ACTION_FILE_WRITE not in _actions(contract)
    assert not contract.requires_file_write


def test_stop_verifier_allows_write_inside_template_save_dir() -> None:
    contract = build_task_contract(RESEARCH_PROMPT)
    ledger = ToolLedger(
        (
            ToolEffect(
                action="file.write",
                effect="file_written",
                name="file_manager",
                status="completed",
                target_type="file",
                target="data/workspace/research/openbot-daily/2026-05-20-01-topic.md",
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
            ToolEffect(
                action="file.write",
                effect="file_written",
                name="file_manager",
                status="completed",
                target_type="file",
                target="data/diaries/2026/05/2026-05-20.md",
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
            "effects": [
                {
                    "action": "file.write",
                    "effect": "file_written",
                    "name": "file_manager",
                    "status": "completed",
                    "target_type": "file",
                    "target": "data/workspace/research/openbot-daily/2026-05-20-01-topic.md",
                }
            ],
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
                "effects": [
                    {
                        "action": "schedule.create",
                        "effect": "schedule_created",
                        "name": "schedule_manager",
                        "status": "completed",
                        "target_type": "schedule",
                        "target": "abc",
                    }
                ],
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
                "effects": [
                    {
                        "action": "command.execute",
                        "effect": "none",
                        "name": "bash",
                        "status": "timeout",
                    }
                ],
            },
        ]
    )

    assert ledger.events[0].status == "timeout"
    assert ledger.has_problem_events()


def test_ledger_preserves_failed_tool_with_empty_effects() -> None:
    contract = build_task_contract("帮我查一下")
    ledger = ledger_from_tool_calls(
        [
            {
                "name": "custom_tool",
                "is_error": True,
                "result_preview": "custom failure",
                "effects": [],
            },
        ]
    )

    decision = verify_stop(contract, "已完成。", ledger)

    assert not decision.allow
    assert "custom failure" in decision.message
