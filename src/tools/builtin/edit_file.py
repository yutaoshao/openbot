"""Incremental project file editing tool."""

from __future__ import annotations

import difflib
from typing import TYPE_CHECKING, Any, Self

from pydantic import Field, field_validator, model_validator

from src.tools.builtin.path_utils import project_root, resolve_project_path
from src.tools.builtin.validation import StrictToolInput, schema_for, validate_args
from src.tools.registry import ToolResult

if TYPE_CHECKING:
    from pathlib import Path

STATUS_COMPLETED = "completed"
STATUS_ERROR = "error"
EFFECT_NONE = "none"
EFFECT_WRITTEN = "written"


class EditFileInput(StrictToolInput):
    """Input model for incremental file edits."""

    file_path: str = Field(min_length=1)
    old_text: str | None = None
    new_text: str | None = None
    line_start: int | None = Field(default=None, ge=1)
    line_end: int | None = Field(default=None, ge=1)
    replacement: str | None = None

    @field_validator("file_path", "old_text", mode="after")
    @classmethod
    def _strip_required_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not value.strip():
            raise ValueError("value must not be empty")
        return value

    @model_validator(mode="after")
    def _validate_mode(self) -> Self:
        text_mode = self.old_text is not None or self.new_text is not None
        line_mode = any(
            value is not None
            for value in (self.line_start, self.line_end, self.replacement)
        )
        if text_mode == line_mode:
            raise ValueError("provide exactly one edit mode")
        if text_mode:
            self._require_text_mode()
        if line_mode:
            self._require_line_mode()
        return self

    def _require_text_mode(self) -> None:
        if self.old_text is None or self.new_text is None:
            raise ValueError("old_text and new_text are required together")

    def _require_line_mode(self) -> None:
        if self.line_start is None or self.line_end is None or self.replacement is None:
            raise ValueError("line_start, line_end, and replacement are required together")
        if self.line_end < self.line_start:
            raise ValueError("line_end must be greater than or equal to line_start")


class EditFileTool:
    """Apply targeted edits to text files under the project root."""

    def __init__(self, root: Path | None = None) -> None:
        self._root = root

    @property
    def name(self) -> str:
        return "edit_file"

    @property
    def description(self) -> str:
        return (
            f"Edits a specific text file under project root {project_root(self._root)} "
            "by exact old/new text replacement or an inclusive line range. "
            "Use when only a targeted file section should change and a whole-file rewrite "
            "would waste context or risk unrelated edits. "
            "Do not use when the file is binary, outside the project root, missing, a "
            "directory, or when codebase-wide search or shell commands are needed."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return schema_for(EditFileInput)

    @property
    def category(self) -> str:
        return "filesystem"

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        data, error = validate_args(EditFileInput, args, tool_name=self.name)
        if error or data is None:
            return error or ToolResult(content="Invalid arguments", is_error=True)
        target, error = resolve_project_path(self._root, data.file_path, operation=self.name)
        if error or target is None:
            return error or ToolResult(content="Invalid path", is_error=True)
        return self._edit_target(target, data)

    def _edit_target(self, target: Path, data: EditFileInput) -> ToolResult:
        if target.is_dir():
            return _error(data.file_path, "Path is a directory", mode=_mode(data))
        if not target.is_file():
            return _error(data.file_path, f"File not found: {data.file_path}", mode=_mode(data))
        try:
            content = target.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return _error(
                data.file_path,
                f"Cannot edit binary file: {data.file_path}",
                mode=_mode(data),
            )
        except OSError as exc:
            return _error(data.file_path, f"Read failed: {exc}", mode=_mode(data))
        return self._apply_edit(target, data, content)

    def _apply_edit(self, target: Path, data: EditFileInput, content: str) -> ToolResult:
        if data.old_text is not None:
            return _apply_old_text_edit(target, data, content)
        return _apply_line_range_edit(target, data, content)


def _apply_old_text_edit(target: Path, data: EditFileInput, content: str) -> ToolResult:
    old_text = data.old_text or ""
    match_count = content.count(old_text)
    if match_count == 0:
        return _error(data.file_path, "old_text not found", mode="old_text")
    if match_count > 1:
        return _error(
            data.file_path,
            f"old_text matched {match_count} times",
            mode="old_text",
            match_count=match_count,
        )
    new_content = content.replace(old_text, data.new_text or "", 1)
    return _write_edit(target, data, content, new_content, "old_text")


def _apply_line_range_edit(target: Path, data: EditFileInput, content: str) -> ToolResult:
    lines = content.splitlines(keepends=True)
    line_start = data.line_start or 1
    line_end = data.line_end or 1
    if line_start > len(lines) or line_end > len(lines):
        return _error(data.file_path, "line range is outside file", mode="line_range")
    selected = lines[line_start - 1 : line_end]
    replacement = _line_replacement_text(data.replacement or "", selected)
    new_content = "".join([*lines[: line_start - 1], replacement, *lines[line_end:]])
    return _write_edit(target, data, content, new_content, "line_range")


def _line_replacement_text(replacement: str, selected: list[str]) -> str:
    if not replacement:
        return replacement
    selected_ended_with_newline = bool(selected and selected[-1].endswith("\n"))
    if selected_ended_with_newline and not replacement.endswith("\n"):
        return replacement + "\n"
    return replacement


def _write_edit(
    target: Path,
    data: EditFileInput,
    content: str,
    new_content: str,
    mode: str,
) -> ToolResult:
    try:
        target.write_text(new_content, encoding="utf-8")
    except OSError as exc:
        return _error(data.file_path, f"Write failed: {exc}", mode=mode)
    metadata = _metadata(data.file_path, STATUS_COMPLETED, EFFECT_WRITTEN, mode)
    metadata.update(_line_metadata(data))
    return ToolResult(
        content=f"Edited {data.file_path}\n{_diff(data.file_path, content, new_content)}",
        metadata=metadata,
    )


def _diff(path: str, before: str, after: str) -> str:
    return "\n".join(
        difflib.unified_diff(
            before.splitlines(),
            after.splitlines(),
            fromfile=f"{path} before",
            tofile=f"{path} after",
            lineterm="",
        )
    )


def _mode(data: EditFileInput) -> str:
    return "old_text" if data.old_text is not None else "line_range"


def _line_metadata(data: EditFileInput) -> dict[str, int]:
    if data.line_start is None or data.line_end is None:
        return {}
    return {"line_start": data.line_start, "line_end": data.line_end}


def _error(path: str, content: str, *, mode: str, **extra: Any) -> ToolResult:
    return ToolResult(
        content=content,
        is_error=True,
        metadata={**_metadata(path, STATUS_ERROR, EFFECT_NONE, mode), **extra},
    )


def _metadata(path: str, status: str, effect: str, mode: str) -> dict[str, Any]:
    return {
        "operation": "edit_file",
        "path": path,
        "status": status,
        "effect": effect,
        "mode": mode,
    }
