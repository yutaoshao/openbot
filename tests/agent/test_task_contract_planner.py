from __future__ import annotations

from src.agent.runtime.write_retry import needs_file_write_retry
from src.agent.state.task_contract import ACTION_FILE_WRITE, ACTION_SCHEDULE_CREATE
from src.agent.state.task_contract_planner import (
    plan_scheduled_task_contract,
    plan_task_contract,
)
from src.infrastructure.model_gateway import ModelResponse


class PlannerGateway:
    async def chat(self, *_args, **_kwargs):
        return ModelResponse(
            text=(
                '{"required_actions": ['
                '{"action": "file.write", '
                '"target_paths": ["data/workspace/leetcode-hot100-plan.md"]}'
                '], "confidence": 0.92}'
            )
        )


class GuessedPathGateway:
    async def chat(self, *_args, **_kwargs):
        return ModelResponse(
            text=(
                '{"required_actions": ['
                '{"action": "file.write", '
                '"target_paths": ["data/reading_notes/人类简史－读书笔记.md"]}'
                '], "confidence": 0.96}'
            )
        )


class SchedulerPromptGateway:
    async def chat(self, *_args, **_kwargs):
        return ModelResponse(
            text=(
                '{"required_actions": ['
                '{"action": "schedule.create"}, '
                '{"action": "file.write", '
                '"allowed_write_dirs": ["data/workspace/research/openbot-daily/"]}'
                '], "confidence": 0.94}'
            )
        )


async def test_planner_model_can_require_file_write_for_contextual_update() -> None:
    contract = await plan_task_contract(
        PlannerGateway(),
        "你更新一下这份计划，每一题都带上题号",
        messages=[
            {"role": "assistant", "content": "已保存到 `data/workspace/leetcode-hot100-plan.md`"},
            {"role": "user", "content": "你更新一下这份计划，每一题都带上题号"},
        ],
        task_state=None,
    )

    requirement = contract.requirement_for(ACTION_FILE_WRITE)

    assert requirement is not None
    assert requirement.target_paths == ("data/workspace/leetcode-hot100-plan.md",)


async def test_planner_does_not_enforce_model_guessed_file_path() -> None:
    contract = await plan_task_contract(
        GuessedPathGateway(),
        "#人类简史－读书笔记\n第二章 我们最早的先人\n没人知道当时真实的情况是什么样的。",
        messages=[
            {"role": "user", "content": "#人类简史－读书笔记\n第一章 舞台布景"},
            {"role": "user", "content": "把我刚刚的笔记保存到读书笔记文件夹中"},
        ],
        task_state=None,
    )

    requirement = contract.requirement_for(ACTION_FILE_WRITE)

    assert requirement is not None
    assert requirement.target_paths == ()


async def test_planner_accepts_actual_write_when_model_path_was_guessed() -> None:
    contract = await plan_task_contract(
        GuessedPathGateway(),
        "#人类简史－读书笔记\n第二章 我们最早的先人\n没人知道当时真实的情况是什么样的。",
        messages=[
            {"role": "user", "content": "#人类简史－读书笔记\n第一章 舞台布景"},
            {"role": "user", "content": "把我刚刚的笔记保存到读书笔记文件夹中"},
        ],
        task_state=None,
    )
    tool_calls = [
        {
            "name": "file_manager",
            "is_error": False,
            "effects": [
                {
                    "action": "file.write",
                    "effect": "file_written",
                    "name": "file_manager",
                    "status": "completed",
                    "target_type": "file",
                    "target": "data/reading_notes/人类简史.md",
                }
            ],
        }
    ]

    assert not needs_file_write_retry(contract, tool_calls)


async def test_scheduled_task_planner_does_not_require_schedule_creation() -> None:
    contract = await plan_scheduled_task_contract(
        SchedulerPromptGateway(),
        "每天早上 3 点，针对 OpenBot 做技术调研，并保存到 "
        "data/workspace/research/openbot-daily/YYYY-MM-DD.md",
        messages=[],
        task_state=None,
    )
    actions = {requirement.action for requirement in contract.required_actions}

    assert ACTION_SCHEDULE_CREATE not in actions
    assert ACTION_FILE_WRITE in actions
