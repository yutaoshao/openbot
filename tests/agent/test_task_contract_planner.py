from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from src.agent.runtime.file_write_verification import file_write_verification_failure
from src.agent.state.task_contract import ACTION_FILE_WRITE, ACTION_SCHEDULE_CREATE
from src.agent.state.task_contract_planner import (
    plan_scheduled_task_contract,
    plan_task_contract,
)
from src.agent.state.task_contract_resources import resolve_contract_resources
from src.infrastructure.model_gateway import ModelResponse
from tests.file_mutation_facts import (
    appended_file_effect,
    created_file_effect,
    executed_mutation_call,
)

if TYPE_CHECKING:
    from pathlib import Path


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


class MisclassifiedDiscussionGateway:
    async def chat(self, *_args, **_kwargs):
        return ModelResponse(
            text=(
                '{"required_actions": ['
                '{"action": "file.write", "target_paths": ["data/AI 八股.md"]}'
                '], "confidence": 0.99}'
            )
        )


class RootGuessGateway:
    async def chat(self, *_args, **_kwargs):
        return ModelResponse(
            text=(
                '{"required_actions": ['
                '{"action": "file.write", "target_paths": ["AI 八股.md"], '
                '"allowed_write_dirs": ["."]}'
                '], "confidence": 0.99}'
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


@pytest.mark.parametrize(
    "user_input",
    (
        "你用的是什么工具保存进去的？",
        "你没有保存错误，AI 八股.md 指的就是data/AI 八股.md。",
        "请问你刚才保存了吗？",
    ),
)
async def test_planner_cannot_add_file_write_to_explicit_discussion(user_input: str) -> None:
    contract = await plan_task_contract(
        MisclassifiedDiscussionGateway(),
        user_input,
        messages=[
            {"role": "assistant", "content": "已保存到 data/AI 八股.md"},
            {"role": "user", "content": user_input},
        ],
        task_state=None,
    )

    assert contract.requirement_for(ACTION_FILE_WRITE) is None


async def test_planner_rejects_root_guess_and_resolves_explicit_file_alias(
    tmp_path: Path,
) -> None:
    target = tmp_path / "data" / "AI 八股.md"
    target.parent.mkdir()
    target.write_text("existing\n", encoding="utf-8")
    user_input = (
        "记住，当我复述我学到的 AI 八股的时候，你除了帮我润色总结之外，还要加到 AI 八股.md 里面去。"
    )
    contract = await plan_task_contract(
        RootGuessGateway(),
        user_input,
        messages=[{"role": "user", "content": user_input}],
        task_state=None,
    )
    resolved_contract = resolve_contract_resources(contract, tmp_path)
    requirement = resolved_contract.requirement_for(ACTION_FILE_WRITE)
    effect = appended_file_effect(tmp_path, "data/AI 八股.md")

    assert requirement is not None
    assert requirement.target_paths == ("data/AI 八股.md",)
    assert requirement.allowed_write_dirs == ()
    assert (
        file_write_verification_failure(
            resolved_contract,
            [executed_mutation_call(effect)],
            project_root=tmp_path,
        )
        is None
    )


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


async def test_planner_accepts_actual_write_when_model_path_was_guessed(tmp_path: Path) -> None:
    contract = await plan_task_contract(
        GuessedPathGateway(),
        "#人类简史－读书笔记\n第二章 我们最早的先人\n没人知道当时真实的情况是什么样的。",
        messages=[
            {"role": "user", "content": "#人类简史－读书笔记\n第一章 舞台布景"},
            {"role": "user", "content": "把我刚刚的笔记保存到读书笔记文件夹中"},
        ],
        task_state=None,
    )
    effect = created_file_effect(tmp_path, "data/reading_notes/人类简史.md")

    assert (
        file_write_verification_failure(
            contract,
            [executed_mutation_call(effect)],
            project_root=tmp_path,
        )
        is None
    )


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
