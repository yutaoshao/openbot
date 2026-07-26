from __future__ import annotations

from typing import TYPE_CHECKING

from src.agent.runtime.file_write_verification import file_write_verification_failure
from src.agent.state.task_contract import (
    ACTION_ANSWER,
    ACTION_FILE_WRITE,
    TaskContract,
    TaskRequirement,
)
from src.agent.state.task_contract_resources import resolve_contract_resources
from src.agent.verification.stop import ToolLedger, verify_stop
from src.tools.effects import ToolEffect
from tests.file_mutation_facts import (
    appended_file_effect,
    created_file_effect,
    executed_mutation_call,
)

if TYPE_CHECKING:
    from pathlib import Path


def _contract_for(path: str) -> TaskContract:
    return TaskContract(
        "write target",
        (
            TaskRequirement(ACTION_ANSWER),
            TaskRequirement(ACTION_FILE_WRITE, "file", "", (path,)),
        ),
    )


def _contract_for_file_and_directory(path: str, directory: str) -> TaskContract:
    return TaskContract(
        "write target in directory",
        (
            TaskRequirement(ACTION_ANSWER),
            TaskRequirement(
                ACTION_FILE_WRITE,
                "file",
                "",
                (path,),
                (directory,),
            ),
        ),
    )


def test_stop_verifier_accepts_unique_alias_after_contract_resolution(tmp_path: Path) -> None:
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "TODO.md").write_text("todo", encoding="utf-8")
    contract = resolve_contract_resources(_contract_for("TODO.md"), tmp_path)

    ledger = ToolLedger((appended_file_effect(tmp_path, "data/TODO.md"),))
    decision = verify_stop(
        contract,
        "已保存到 data/TODO.md。",
        ledger,
        project_root=tmp_path,
    )

    assert decision.allow


def test_stop_verifier_rejects_ambiguous_file_target_with_reason(tmp_path: Path) -> None:
    (tmp_path / "data").mkdir()
    (tmp_path / "docs").mkdir()
    (tmp_path / "data" / "TODO.md").write_text("data", encoding="utf-8")
    (tmp_path / "docs" / "TODO.md").write_text("docs", encoding="utf-8")
    contract = resolve_contract_resources(_contract_for("TODO.md"), tmp_path)

    ledger = ToolLedger((appended_file_effect(tmp_path, "data/TODO.md"),))
    decision = verify_stop(contract, "已保存。", ledger, project_root=tmp_path)

    assert not decision.allow
    assert "文件目标不明确" in decision.message
    assert "data/TODO.md" in decision.message
    assert "docs/TODO.md" in decision.message


def test_stop_verifier_reports_expected_and_observed_file_targets(tmp_path: Path) -> None:
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "TODO.md").write_text("todo", encoding="utf-8")
    contract = resolve_contract_resources(_contract_for("data/TODO.md"), tmp_path)

    ledger = ToolLedger((created_file_effect(tmp_path, "docs/TODO.md"),))
    decision = verify_stop(contract, "已保存。", ledger, project_root=tmp_path)

    assert not decision.allow
    assert "期望写入 data/TODO.md" in decision.message
    assert "实际写入 docs/TODO.md" in decision.message


def test_file_write_verification_accepts_unique_alias_mutation(tmp_path: Path) -> None:
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "TODO.md").write_text("todo", encoding="utf-8")
    contract = resolve_contract_resources(_contract_for("TODO.md"), tmp_path)
    effect = appended_file_effect(tmp_path, "data/TODO.md")

    assert (
        file_write_verification_failure(
            contract,
            [executed_mutation_call(effect)],
            project_root=tmp_path,
        )
        is None
    )


def test_exact_target_and_project_root_accept_verified_append(tmp_path: Path) -> None:
    target = tmp_path / "data" / "AI 八股.md"
    target.parent.mkdir()
    target.write_text("existing\n", encoding="utf-8")
    contract = resolve_contract_resources(
        _contract_for_file_and_directory("data/AI 八股.md", "."),
        tmp_path,
    )
    effect = appended_file_effect(tmp_path, "data/AI 八股.md")
    ledger = ToolLedger((effect,))

    decision = verify_stop(contract, "已追加到 data/AI 八股.md。", ledger, project_root=tmp_path)

    assert contract.allowed_write_dirs == ("./",)
    assert decision.allow
    assert (
        file_write_verification_failure(
            contract,
            [executed_mutation_call(effect)],
            project_root=tmp_path,
        )
        is None
    )


def test_project_root_failure_message_does_not_report_target_mismatch(tmp_path: Path) -> None:
    contract = resolve_contract_resources(
        _contract_for_file_and_directory("data/AI 八股.md", "./"),
        tmp_path,
    )
    unverified_write = ToolEffect(
        action="file.append",
        status="completed",
        effect="file_written",
        target_type="file",
        target="data/AI 八股.md",
        name="append_file",
    )

    decision = verify_stop(
        contract,
        "已追加。",
        ToolLedger((unverified_write,)),
        project_root=tmp_path,
    )

    assert not decision.allow
    assert "凭证或最终后置条件验证失败" in decision.message
    assert "写入目标不匹配" not in decision.message
