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
