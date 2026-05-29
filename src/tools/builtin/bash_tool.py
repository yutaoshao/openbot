"""Local shell execution tool."""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from pydantic import Field, field_validator

from src.tools.builtin.path_utils import project_root
from src.tools.builtin.validation import StrictToolInput, schema_for, validate_args
from src.tools.effects import (
    EFFECT_NONE,
    STATUS_COMPLETED,
    STATUS_ERROR,
    STATUS_TIMEOUT,
    tool_effect,
)
from src.tools.registry import ToolResult

EFFECT_COMMAND_EXECUTED = "command_executed"


class BashInput(StrictToolInput):
    """Input model for local shell execution."""

    description: str = Field(min_length=1)
    command: str = Field(min_length=1)
    cwd: str = "."
    timeout_seconds: float | None = Field(default=None, gt=0)

    @field_validator("description", "command", "cwd", mode="after")
    @classmethod
    def _require_non_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("value must not be empty")
        return value


class BashTool:
    """Execute local shell commands from the project environment."""

    def __init__(self, root: Path | None = None) -> None:
        self._root = root

    @property
    def name(self) -> str:
        return "bash"

    @property
    def description(self) -> str:
        return (
            "Runs a local shell command with full host permissions and returns stdout, "
            "stderr, and exit status. "
            "Use when the task needs system commands such as git, ls, cat, package "
            "managers, tests, or other project automation. "
            "Do not use when Python-only deterministic computation fits code_executor, "
            "or when a safer dedicated file search or edit tool can do the job."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return schema_for(BashInput)

    @property
    def category(self) -> str:
        return "execution"

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        data, error = validate_args(BashInput, args, tool_name=self.name)
        if error or data is None:
            return error or ToolResult(content="Invalid arguments", is_error=True)
        cwd, error = _resolve_cwd(project_root(self._root), data.cwd)
        if error:
            return error
        return await _run_command(data.command, cwd, data.timeout_seconds)


async def _run_command(command: str, cwd: Path, timeout: float | None) -> ToolResult:
    process = await asyncio.create_subprocess_shell(
        command,
        cwd=str(cwd),
        executable=_shell(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except TimeoutError:
        process.kill()
        await process.communicate()
        return ToolResult(
            content=f"Command timed out after {timeout:.2f}s",
            is_error=True,
            metadata={"cwd": str(cwd), "exit_code": None},
            effects=(_effect(cwd, None, STATUS_TIMEOUT, EFFECT_NONE),),
        )
    return _process_result(cwd, process.returncode or 0, stdout, stderr)


def _process_result(
    cwd: Path,
    exit_code: int,
    stdout: bytes,
    stderr: bytes,
) -> ToolResult:
    stdout_text = stdout.decode("utf-8", errors="replace")
    stderr_text = stderr.decode("utf-8", errors="replace")
    is_error = exit_code != 0
    return ToolResult(
        content=_format_output(stdout_text, stderr_text),
        is_error=is_error,
        metadata={"cwd": str(cwd), "exit_code": exit_code},
        effects=(
            _effect(
                cwd,
                exit_code,
                STATUS_ERROR if is_error else STATUS_COMPLETED,
                EFFECT_NONE if is_error else EFFECT_COMMAND_EXECUTED,
            ),
        ),
    )


def _format_output(stdout: str, stderr: str) -> str:
    parts = []
    if stdout:
        parts.append(f"Stdout:\n{stdout.rstrip()}")
    if stderr:
        parts.append(f"Stderr:\n{stderr.rstrip()}")
    return "\n".join(parts) if parts else "(no output)"


def _resolve_cwd(root: Path, cwd: str) -> tuple[Path | None, ToolResult | None]:
    try:
        candidate = Path(os.path.expandvars(cwd)).expanduser()
        target = candidate if candidate.is_absolute() else root / candidate
        resolved = target.resolve()
    except (OSError, RuntimeError) as exc:
        return None, _cwd_error(f"Invalid cwd: {exc}")
    if not resolved.is_dir():
        return None, _cwd_error(f"cwd is not a directory: {cwd}")
    return resolved, None


def _cwd_error(content: str) -> ToolResult:
    return ToolResult(
        content=content,
        is_error=True,
        effects=(
            tool_effect(
                "command.execute",
                EFFECT_NONE,
                status=STATUS_ERROR,
                name="bash",
            ),
        ),
    )


def _effect(cwd: Path, exit_code: int | None, status: str, effect: str):
    return tool_effect(
        "command.execute",
        effect,
        status=status,
        target_type="cwd",
        target=str(cwd),
        name="bash",
        exit_code=exit_code,
    )


def _shell() -> str:
    for candidate in (os.environ.get("SHELL"), "/bin/zsh", "/bin/bash", "/bin/sh"):
        if candidate and Path(candidate).is_file():
            return candidate
    shell = shutil.which("sh")
    if shell:
        return shell
    raise RuntimeError("No shell executable found")
