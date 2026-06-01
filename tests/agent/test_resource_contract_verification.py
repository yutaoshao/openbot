from __future__ import annotations

from typing import TYPE_CHECKING

from src.agent.runtime.write_retry import needs_file_write_retry
from src.agent.state.task_contract import (
    ACTION_ANSWER,
    ACTION_FILE_WRITE,
    TaskContract,
    TaskRequirement,
)
from src.agent.state.task_contract_resources import resolve_contract_resources
from src.agent.verification.stop import ToolLedger, verify_stop
from src.tools.effects import ToolEffect

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


def _written_file(path: str) -> ToolLedger:
    return ToolLedger(
        (
            ToolEffect(
                action="file.write",
                effect="file_written",
                status="completed",
                target_type="file",
                target=path,
            ),
        )
    )


def test_stop_verifier_accepts_unique_alias_after_contract_resolution(tmp_path: Path) -> None:
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "TODO.md").write_text("todo", encoding="utf-8")
    contract = resolve_contract_resources(_contract_for("TODO.md"), tmp_path)

    decision = verify_stop(contract, "已保存到 data/TODO.md。", _written_file("data/TODO.md"))

    assert decision.allow


def test_stop_verifier_rejects_ambiguous_file_target_with_reason(tmp_path: Path) -> None:
    (tmp_path / "data").mkdir()
    (tmp_path / "docs").mkdir()
    (tmp_path / "data" / "TODO.md").write_text("data", encoding="utf-8")
    (tmp_path / "docs" / "TODO.md").write_text("docs", encoding="utf-8")
    contract = resolve_contract_resources(_contract_for("TODO.md"), tmp_path)

    decision = verify_stop(contract, "已保存。", _written_file("data/TODO.md"))

    assert not decision.allow
    assert "文件目标不明确" in decision.message
    assert "data/TODO.md" in decision.message
    assert "docs/TODO.md" in decision.message


def test_stop_verifier_reports_expected_and_observed_file_targets(tmp_path: Path) -> None:
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "TODO.md").write_text("todo", encoding="utf-8")
    contract = resolve_contract_resources(_contract_for("data/TODO.md"), tmp_path)

    decision = verify_stop(contract, "已保存。", _written_file("docs/TODO.md"))

    assert not decision.allow
    assert "期望写入 data/TODO.md" in decision.message
    assert "实际写入 docs/TODO.md" in decision.message


def test_runtime_retry_stops_after_unique_alias_write_is_verified(tmp_path: Path) -> None:
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "TODO.md").write_text("todo", encoding="utf-8")
    contract = resolve_contract_resources(_contract_for("TODO.md"), tmp_path)
    tool_calls = [
        {
            "name": "file_manager",
            "is_error": False,
            "effects": [
                {
                    "action": "file.write",
                    "effect": "file_written",
                    "status": "completed",
                    "target_type": "file",
                    "target": "data/TODO.md",
                }
            ],
        }
    ]

    assert not needs_file_write_retry(contract, tool_calls)
