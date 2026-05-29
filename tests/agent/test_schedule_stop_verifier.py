from __future__ import annotations

from src.agent.state.task_contract import (
    ACTION_FILE_WRITE,
    ACTION_SCHEDULE_CREATE,
    ACTION_SCHEDULE_UPDATE,
    build_task_contract,
)
from src.agent.verification.stop import ToolLedger, verify_stop
from src.tools.effects import ToolEffect


def _actions(contract) -> set[str]:
    return {requirement.action for requirement in contract.required_actions}


def _schedule_list_ledger() -> ToolLedger:
    return ToolLedger(
        (
            ToolEffect(
                action="schedule.list",
                effect="schedule_listed",
                name="schedule_manager",
                status="completed",
                target_type="schedule",
                summary="Listed schedules",
            ),
        )
    )


def test_task_contract_treats_schedule_question_as_consultation() -> None:
    contract = build_task_contract(
        "/Users/yutaoshao/Project/openbot/data/diaries/2026/05 "
        "我想把这个日记也改成类似 conversation 的年月文件夹，"
        "然后月份文件夹里面包含当月的日记，需要改哪些地方？"
        "是不是要把定时任务也改一下？再把目录结构也要改一下？"
    )

    assert ACTION_SCHEDULE_UPDATE not in _actions(contract)


def test_stop_verifier_allows_consultation_after_schedule_read() -> None:
    contract = build_task_contract(
        "data/diaries 想改成年月目录，需要改哪些地方？"
        "是不是要把定时任务也改一下？"
    )

    decision = verify_stop(
        contract,
        "需要改日记生成路径、读取路径和定时任务 prompt。",
        _schedule_list_ledger(),
    )

    assert decision.allow


def test_task_contract_ignores_schedule_words_inside_research_examples() -> None:
    contract = build_task_contract(
        """每天早上 3 点，针对 OpenBot 的一个具体功能点做一次技术调研，只产出研究报告，不修改源码。

每次只研究一个功能点，粒度要具体到代码模块/流程，例如：
- schedule_manager 创建和执行定时任务
- file_manager 文件写入确认机制

执行步骤：
1. 读取 `data/workspace/research/openbot-daily/`，根据已有报告决定下一个功能点。
2. 使用 file_manager 保存到：
   `data/workspace/research/openbot-daily/YYYY-MM-DD-NN-topic-slug.md`
"""
    )
    actions = _actions(contract)

    assert ACTION_SCHEDULE_CREATE not in actions
    assert ACTION_FILE_WRITE in actions


def test_stop_verifier_rejects_unconfirmed_schedule_update_claim() -> None:
    contract = build_task_contract("列出定时任务")

    decision = verify_stop(contract, "已更新定时任务。", _schedule_list_ledger())

    assert not decision.allow
    assert "任务操作没有确认成功" in decision.message


def test_stop_verifier_rejects_unconfirmed_schedule_delete_claim() -> None:
    contract = build_task_contract("列出定时任务")

    decision = verify_stop(contract, "已删除定时任务。", _schedule_list_ledger())

    assert not decision.allow
    assert "任务操作没有确认成功" in decision.message
