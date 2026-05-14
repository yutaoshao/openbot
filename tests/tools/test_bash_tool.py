from __future__ import annotations

from typing import TYPE_CHECKING

from src.tools.builtin.bash_tool import BashTool

if TYPE_CHECKING:
    from pathlib import Path


async def test_bash_returns_stdout_and_exit_code(tmp_path: Path) -> None:
    tool = BashTool(root=tmp_path)

    result = await tool.execute(
        {
            "description": "print a small value",
            "command": "printf hello",
        }
    )

    assert not result.is_error
    assert result.content == "Stdout:\nhello"
    assert result.metadata["exit_code"] == 0
    assert result.metadata["cwd"] == str(tmp_path.resolve())


async def test_bash_returns_error_for_non_zero_exit_with_stderr(tmp_path: Path) -> None:
    tool = BashTool(root=tmp_path)

    result = await tool.execute(
        {
            "description": "show command failure",
            "command": "printf problem >&2; exit 7",
        }
    )

    assert result.is_error
    assert "Stderr:\nproblem" in result.content
    assert result.metadata["exit_code"] == 7
    assert result.metadata["status"] == "error"


async def test_bash_uses_requested_cwd(tmp_path: Path) -> None:
    (tmp_path / "nested").mkdir()
    tool = BashTool(root=tmp_path)

    result = await tool.execute(
        {
            "description": "show working directory",
            "command": "pwd",
            "cwd": "nested",
        }
    )

    assert not result.is_error
    assert result.content == f"Stdout:\n{tmp_path / 'nested'}"
    assert result.metadata["cwd"] == str((tmp_path / "nested").resolve())


async def test_bash_rejects_empty_command(tmp_path: Path) -> None:
    tool = BashTool(root=tmp_path)

    result = await tool.execute({"description": "empty command", "command": "   "})

    assert result.is_error
    assert "Invalid arguments for bash" in result.content
    assert result.metadata["status"] == "validation_error"


async def test_bash_reports_timeout(tmp_path: Path) -> None:
    tool = BashTool(root=tmp_path)

    result = await tool.execute(
        {
            "description": "sleep briefly",
            "command": "sleep 2",
            "timeout_seconds": 0.01,
        }
    )

    assert result.is_error
    assert "timed out" in result.content
    assert result.metadata["status"] == "timeout"
