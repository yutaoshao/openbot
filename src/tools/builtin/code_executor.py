"""Sandboxed Python code execution tool."""

from __future__ import annotations

import asyncio
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from src.tools.effects import (
    EFFECT_NONE,
    STATUS_COMPLETED,
    STATUS_ERROR,
    STATUS_TIMEOUT,
    tool_effect,
)
from src.tools.registry import ToolResult

# Safety: maximum execution time in seconds
MAX_TIMEOUT = 30


class CodeExecutorTool:
    """Execute Python code in a sandboxed subprocess."""

    @property
    def name(self) -> str:
        return "code_executor"

    @property
    def description(self) -> str:
        return (
            "Executes short Python code in an isolated subprocess and returns "
            "stdout, stderr, and exit status. "
            "Use when you need calculations, data transformation, parsing, or a quick "
            "logic check that Python can answer deterministically. "
            "Do not use when the task needs shell commands, git/system operations, "
            "long-running services, network credentials, or workspace file editing."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "Python code to execute",
                },
                "timeout": {
                    "type": "integer",
                    "description": (
                        f"Execution timeout in seconds (default: 10, max: {MAX_TIMEOUT})"
                    ),
                    "default": 10,
                },
            },
            "required": ["code"],
        }

    @property
    def category(self) -> str:
        return "execution"

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        code = args.get("code", "")
        timeout = min(args.get("timeout", 10), MAX_TIMEOUT)

        if not code.strip():
            return _result("No code provided", True, STATUS_ERROR)

        try:
            return _process_result(*(await _run_python(code, timeout)))
        except TimeoutError:
            return _result(f"Execution timed out after {timeout} seconds", True, STATUS_TIMEOUT)
        except Exception as e:
            return _result(f"Execution failed: {e}", True, STATUS_ERROR)


async def _run_python(code: str, timeout: int) -> tuple[int, bytes, bytes]:
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as handle:
        handle.write(code)
        script_path = handle.name
    try:
        process = await asyncio.create_subprocess_exec(
            "python3",
            script_path,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env={"PATH": "/usr/bin:/usr/local/bin"},
        )
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
        return process.returncode or 0, stdout, stderr
    finally:
        Path(script_path).unlink(missing_ok=True)


def _process_result(exit_code: int, stdout: bytes, stderr: bytes) -> ToolResult:
    stdout_text = stdout.decode("utf-8", errors="replace")
    stderr_text = stderr.decode("utf-8", errors="replace")
    if exit_code != 0:
        return _failed_result(exit_code, stdout_text, stderr_text)
    output = stdout_text or "(no output)"
    if stderr_text:
        output += f"\nStderr:\n{stderr_text}"
    return ToolResult(
        content=output.strip(),
        metadata={"exit_code": 0},
        effects=(_effect(STATUS_COMPLETED, "code_executed", 0),),
    )


def _failed_result(exit_code: int, stdout: str, stderr: str) -> ToolResult:
    output = f"Exit code: {exit_code}\n"
    if stdout:
        output += f"Stdout:\n{stdout}\n"
    output += f"Stderr:\n{stderr}"
    return ToolResult(
        content=output.strip(),
        is_error=True,
        metadata={"exit_code": exit_code},
        effects=(_effect(STATUS_ERROR, EFFECT_NONE, exit_code),),
    )


def _result(content: str, is_error: bool, status: str) -> ToolResult:
    return ToolResult(content=content, is_error=is_error, effects=(_effect(status, EFFECT_NONE),))


def _effect(status: str, effect: str, exit_code: int | None = None):
    return tool_effect(
        "code.execute",
        effect,
        status=status,
        target_type="runtime",
        target="python",
        name="code_executor",
        exit_code=exit_code,
    )
