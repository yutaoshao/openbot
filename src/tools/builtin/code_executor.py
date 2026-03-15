"""Sandboxed Python code execution tool."""

from __future__ import annotations

import asyncio
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from src.tools.registry import ToolResult

# Safety: maximum execution time in seconds
MAX_TIMEOUT = 30
# Safety: maximum output size in characters
MAX_OUTPUT = 10000


class CodeExecutorTool:
    """Execute Python code in a sandboxed subprocess."""

    @property
    def name(self) -> str:
        return "code_executor"

    @property
    def description(self) -> str:
        return (
            "Execute Python code and return the output. "
            "Code runs in an isolated subprocess with a timeout. "
            "Use for calculations, data processing, or testing logic."
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
            return ToolResult(content="No code provided", is_error=True)

        try:
            # Write code to a temp file and run in subprocess
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".py", delete=False
            ) as f:
                f.write(code)
                script_path = f.name

            try:
                process = await asyncio.create_subprocess_exec(
                    "python3", script_path,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    # Isolate: no inherited env except PATH
                    env={"PATH": "/usr/bin:/usr/local/bin"},
                )

                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=timeout,
                )
            finally:
                Path(script_path).unlink(missing_ok=True)

            stdout_text = stdout.decode("utf-8", errors="replace")[:MAX_OUTPUT]
            stderr_text = stderr.decode("utf-8", errors="replace")[:MAX_OUTPUT]

            if process.returncode != 0:
                output = f"Exit code: {process.returncode}\n"
                if stdout_text:
                    output += f"Stdout:\n{stdout_text}\n"
                output += f"Stderr:\n{stderr_text}"
                return ToolResult(
                    content=output.strip(),
                    is_error=True,
                    metadata={"exit_code": process.returncode},
                )

            output = stdout_text or "(no output)"
            if stderr_text:
                output += f"\nStderr:\n{stderr_text}"

            return ToolResult(
                content=output.strip(),
                metadata={"exit_code": 0},
            )

        except TimeoutError:
            return ToolResult(
                content=f"Execution timed out after {timeout} seconds",
                is_error=True,
            )
        except Exception as e:
            return ToolResult(content=f"Execution failed: {e}", is_error=True)
