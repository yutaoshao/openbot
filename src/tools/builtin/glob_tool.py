"""File glob search tool backed by ripgrep."""

from __future__ import annotations

import asyncio
import shutil
import subprocess
from typing import TYPE_CHECKING, Any

from pydantic import Field, field_validator

from src.tools.builtin.path_utils import project_root, relative_to_root, resolve_project_path
from src.tools.builtin.validation import StrictToolInput, schema_for, validate_args
from src.tools.effects import (
    EFFECT_NONE,
    STATUS_COMPLETED,
    STATUS_ERROR,
    STATUS_MISSING_DEPENDENCY,
    tool_effect,
)
from src.tools.registry import ToolResult

if TYPE_CHECKING:
    from pathlib import Path

DEFAULT_MAX_RESULTS = 200
RG_TIMEOUT_SECONDS = 30
EFFECT_FILES_MATCHED = "files_matched"


class GlobInput(StrictToolInput):
    """Input model for file glob searches."""

    pattern: str = Field(min_length=1)
    path: str = "."
    max_results: int = Field(default=DEFAULT_MAX_RESULTS, ge=1)

    @field_validator("pattern", "path", mode="after")
    @classmethod
    def _require_non_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("value must not be empty")
        return value


class GlobTool:
    """Search project files by glob pattern."""

    def __init__(self, root: Path | None = None) -> None:
        self._root = root

    @property
    def name(self) -> str:
        return "glob"

    @property
    def description(self) -> str:
        return (
            f"Finds files under project root {project_root(self._root)} using ripgrep "
            "file discovery and gitignore-aware glob patterns. "
            "Use when you need a controlled file list such as **/*.py or src/**/*.ts "
            "before reading, grepping, or editing files. "
            "Do not use when matching file contents, executing shell commands, or "
            "accessing paths outside the project root."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return schema_for(GlobInput)

    @property
    def category(self) -> str:
        return "filesystem"

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        data, error = validate_args(GlobInput, args, tool_name=self.name)
        if error or data is None:
            return error or ToolResult(content="Invalid arguments", is_error=True)
        if shutil.which("rg") is None:
            return _missing_rg()
        target, error = resolve_project_path(self._root, data.path, operation=self.name)
        if error or target is None:
            return error or ToolResult(content="Invalid path", is_error=True)
        return await self._run_rg(data, target)

    async def _run_rg(self, data: GlobInput, target: Path) -> ToolResult:
        if not target.is_dir():
            return _error(data.path, f"Not a directory: {data.path}")
        rel_path = relative_to_root(self._root, target)
        cmd = ["rg", "--files", "-g", data.pattern]
        if rel_path != ".":
            cmd.append(rel_path)
        return await _execute_rg(cmd, project_root(self._root), data)


async def _execute_rg(cmd: list[str], cwd: Path, data: GlobInput) -> ToolResult:
    process = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(
        process.communicate(),
        timeout=RG_TIMEOUT_SECONDS,
    )
    if process.returncode not in (0, 1):
        return _error(data.path, stderr.decode("utf-8", errors="replace").strip())
    return _glob_result(stdout.decode("utf-8", errors="replace"), data)


def _glob_result(stdout: str, data: GlobInput) -> ToolResult:
    matches = sorted(line for line in stdout.splitlines() if line)
    visible = matches[: data.max_results]
    truncated = len(matches) > len(visible)
    return ToolResult(
        content="\n".join(visible) if visible else "No files matched.",
        metadata={
            "pattern": data.pattern,
            "count": len(visible),
            "truncated": truncated,
        },
        effects=(
            _effect(data.path, STATUS_COMPLETED, EFFECT_FILES_MATCHED, pattern=data.pattern),
        ),
    )


def _missing_rg() -> ToolResult:
    return ToolResult(
        content="ripgrep (rg) is required for glob but was not found on PATH",
        is_error=True,
        effects=(_effect(".", STATUS_MISSING_DEPENDENCY, EFFECT_NONE),),
    )


def _error(path: str, content: str) -> ToolResult:
    return ToolResult(
        content=content,
        is_error=True,
        effects=(_effect(path, STATUS_ERROR, EFFECT_NONE),),
    )


def _effect(path: str, status: str, effect: str, **details: Any):
    return tool_effect(
        "file.glob",
        effect,
        status=status,
        target_type="path",
        target=path,
        name="glob",
        **details,
    )
