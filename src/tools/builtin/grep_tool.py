"""Content grep search tool backed by ripgrep JSON output."""

from __future__ import annotations

import asyncio
import json
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

DEFAULT_MAX_RESULTS = 50
RG_TIMEOUT_SECONDS = 30
EFFECT_CONTENT_MATCHED = "content_matched"


class GrepInput(StrictToolInput):
    """Input model for content searches."""

    pattern: str = Field(min_length=1)
    path: str = "."
    glob: str | None = None
    context_lines: int = Field(default=0, ge=0)
    max_results: int = Field(default=DEFAULT_MAX_RESULTS, ge=1)
    literal: bool = False
    case_sensitive: bool = True

    @field_validator("pattern", "path", "glob", mode="after")
    @classmethod
    def _require_non_blank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("value must not be empty")
        return value


class GrepTool:
    """Search project file contents with ripgrep."""

    def __init__(self, root: Path | None = None) -> None:
        self._root = root

    @property
    def name(self) -> str:
        return "grep"

    @property
    def description(self) -> str:
        return (
            f"Searches text content under project root {project_root(self._root)} "
            "with ripgrep and returns matching lines with file, line, and column. "
            "Use when you need fast keyword or regex search across project files, logs, "
            "or saved tool outputs. "
            "Do not use when you only need file names, semantic search, shell commands, "
            "or paths outside the project root."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return schema_for(GrepInput)

    @property
    def category(self) -> str:
        return "filesystem"

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        data, error = validate_args(GrepInput, args, tool_name=self.name)
        if error or data is None:
            return error or ToolResult(content="Invalid arguments", is_error=True)
        if shutil.which("rg") is None:
            return _missing_rg()
        target, error = resolve_project_path(self._root, data.path, operation=self.name)
        if error or target is None:
            return error or ToolResult(content="Invalid path", is_error=True)
        return await _execute_rg(_build_command(data, target, self._root), self._root, data)


def _build_command(data: GrepInput, target: Path, root: Path | None) -> list[str]:
    cmd = ["rg", "--json", "--line-number", "--column"]
    if data.literal:
        cmd.append("--fixed-strings")
    if not data.case_sensitive:
        cmd.append("--ignore-case")
    if data.context_lines:
        cmd.extend(["--context", str(data.context_lines)])
    if data.glob:
        cmd.extend(["-g", data.glob])
    cmd.extend([data.pattern, relative_to_root(root, target)])
    return cmd


async def _execute_rg(cmd: list[str], root: Path | None, data: GrepInput) -> ToolResult:
    process = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=str(project_root(root)),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(
        process.communicate(),
        timeout=RG_TIMEOUT_SECONDS,
    )
    if process.returncode not in (0, 1):
        return _error(data.path, stderr.decode("utf-8", errors="replace").strip())
    return _grep_result(stdout.decode("utf-8", errors="replace"), data)


def _grep_result(stdout: str, data: GrepInput) -> ToolResult:
    lines, match_count, truncated = _parse_rg_json(
        stdout,
        data.max_results,
        data.context_lines,
    )
    return ToolResult(
        content="\n".join(lines) if lines else "No matches found.",
        metadata={
            "pattern": data.pattern,
            "count": match_count,
            "truncated": truncated,
        },
        effects=(
            _effect(data.path, STATUS_COMPLETED, EFFECT_CONTENT_MATCHED, pattern=data.pattern),
        ),
    )


def _parse_rg_json(
    stdout: str,
    max_results: int,
    context_lines: int = 0,
) -> tuple[list[str], int, bool]:
    lines: list[str] = []
    pending_context: list[dict[str, Any]] = []
    last_visible_match: tuple[str, int] | None = None
    match_count = 0
    truncated = False
    for raw_line in stdout.splitlines():
        event = json.loads(raw_line)
        event_type = event.get("type")
        if event_type == "match":
            match_count += 1
            if match_count > max_results:
                truncated = True
                pending_context.clear()
                continue
            lines.extend(_format_event(context) for context in pending_context)
            pending_context.clear()
            lines.append(_format_event(event))
            last_visible_match = _event_location(event)
            continue
        if event_type != "context":
            continue
        if _is_after_visible_match(event, last_visible_match, context_lines):
            lines.append(_format_event(event))
            continue
        pending_context.append(event)
    return lines, min(match_count, max_results), truncated


def _is_after_visible_match(
    context_event: dict[str, Any],
    last_match: tuple[str, int] | None,
    context_lines: int,
) -> bool:
    if last_match is None:
        return False
    context_path, context_line = _event_location(context_event)
    match_path, match_line = last_match
    return context_path == match_path and match_line < context_line <= match_line + context_lines


def _event_location(event: dict[str, Any]) -> tuple[str, int]:
    data = event["data"]
    return data["path"]["text"], data["line_number"]


def _format_event(event: dict[str, Any]) -> str:
    data = event["data"]
    path = _display_path(data["path"]["text"])
    line_number = data["line_number"]
    text = data["lines"]["text"].rstrip("\n")
    if event["type"] == "context":
        return f"{path}:{line_number}:{text}"
    column = data["submatches"][0]["start"] + 1
    return f"{path}:{line_number}:{column}:{text}"


def _display_path(path: str) -> str:
    return path[2:] if path.startswith("./") else path


def _missing_rg() -> ToolResult:
    return ToolResult(
        content="ripgrep (rg) is required for grep but was not found on PATH",
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
        "file.grep",
        effect,
        status=status,
        target_type="path",
        target=path,
        name="grep",
        **details,
    )
