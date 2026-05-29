from __future__ import annotations

from src.agent.state.task_contract import build_task_contract
from src.agent.verification.stop import ledger_from_tool_calls, verify_stop


def test_stop_verifier_allows_recovered_tool_validation_error() -> None:
    contract = build_task_contract("帮我修改")
    ledger = ledger_from_tool_calls(
        [
            {
                "name": "bash",
                "is_error": True,
                "result_preview": "Invalid arguments for bash: 1 validation error(s)",
                "effects": [
                    {
                        "action": "bash.validate",
                        "status": "validation_error",
                        "effect": "none",
                        "name": "bash",
                    },
                ],
            },
            {
                "name": "bash",
                "is_error": False,
                "result_preview": "pytest passed",
                "effects": [
                    {
                        "action": "command.execute",
                        "status": "completed",
                        "effect": "command_executed",
                        "target_type": "cwd",
                        "target": "/Users/yutaoshao/Project/openbot",
                        "name": "bash",
                    },
                ],
            },
        ],
    )

    decision = verify_stop(contract, "已修改并验证。", ledger)

    assert decision.allow
