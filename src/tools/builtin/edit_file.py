"""Incremental project file editing tool."""

from __future__ import annotations

import difflib
from typing import TYPE_CHECKING, Any, Self

from pydantic import Field, field_validator, model_validator

from src.tools.builtin.path_utils import relative_to_root, resolve_project_path
from src.tools.builtin.validation import StrictToolInput, schema_for, validate_args
from src.tools.effects import EFFECT_NONE, STATUS_ERROR, tool_effect
from src.tools.file_mutation_receipt import FILE_WRITTEN, FileMutationReceipt, content_sha256
from src.tools.file_mutation_service import FileMutationError, FileMutationService
from src.tools.registry import ToolResult

if TYPE_CHECKING:
    from pathlib import Path


class EditFileInput(StrictToolInput):
    """Input model for targeted file edits."""

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
    def _validate_edit_shape(self) -> Self:
        has_exact_text = self.old_text is not None or self.new_text is not None
        has_line_range = any(
            value is not None for value in (self.line_start, self.line_end, self.replacement)
        )
        if has_exact_text == has_line_range:
            raise ValueError("provide exactly one edit form")
        if has_exact_text:
            self._require_exact_text_fields()
        if has_line_range:
            self._require_line_range_fields()
        return self

    def _require_exact_text_fields(self) -> None:
        if self.old_text is None or self.new_text is None:
            raise ValueError("old_text and new_text are required together")

    def _require_line_range_fields(self) -> None:
        if self.line_start is None or self.line_end is None or self.replacement is None:
            raise ValueError("line_start, line_end, and replacement are required together")
        if self.line_end < self.line_start:
            raise ValueError("line_end must be greater than or equal to line_start")


class EditFileTool:
    """Apply targeted edits through the shared file mutation service."""

    def __init__(self, mutation_service: FileMutationService) -> None:
        self._mutations = mutation_service

    @property
    def project_root(self) -> Path:
        return self._mutations.project_root

    @property
    def name(self) -> str:
        return "edit_file"

    @property
    def description(self) -> str:
        return (
            f"Edits a specific UTF-8 text file under project root {self.project_root} "
            "by exact old/new text replacement or an inclusive line range. "
            "Use when only a targeted section should change. "
            "Do not use when Bash or whole-file replacement would be required."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return schema_for(EditFileInput)

    @property
    def category(self) -> str:
        return "filesystem"

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        request, validation_error = validate_args(EditFileInput, args, tool_name=self.name)
        if validation_error is not None:
            return validation_error
        assert request is not None
        target, path_error = resolve_project_path(
            self.project_root,
            request.file_path,
            operation=self.name,
        )
        if path_error is not None:
            return path_error
        assert target is not None
        return self._edit_target(target, request)

    def _edit_target(self, target: Path, request: EditFileInput) -> ToolResult:
        source_content, read_error = self._read_target(target, request.file_path)
        if read_error:
            return read_error
        assert source_content is not None
        if request.old_text is not None:
            return self._replace_exact_text(target, request, source_content)
        return self._replace_line_range(target, request, source_content)

    def _read_target(self, target: Path, path: str) -> tuple[str | None, ToolResult | None]:
        if target.is_dir():
            return None, self._error(target, "Path is a directory")
        if not target.is_file():
            return None, self._error(target, f"File not found: {path}")
        try:
            return target.read_text(encoding="utf-8"), None
        except UnicodeDecodeError:
            return None, self._error(target, f"Cannot edit binary file: {path}")
        except OSError as exc:
            return None, self._error(target, f"Read failed: {exc}")

    def _replace_exact_text(
        self,
        target: Path,
        request: EditFileInput,
        source_content: str,
    ) -> ToolResult:
        old_text = request.old_text or ""
        match_count = source_content.count(old_text)
        if match_count == 0:
            return self._error(target, "old_text not found")
        if match_count > 1:
            return self._error(
                target,
                f"old_text matched {match_count} times",
                match_count=match_count,
            )
        updated_content = source_content.replace(old_text, request.new_text or "", 1)
        return self._commit(target, source_content, updated_content)

    def _replace_line_range(
        self,
        target: Path,
        request: EditFileInput,
        source_content: str,
    ) -> ToolResult:
        lines = source_content.splitlines(keepends=True)
        line_start = request.line_start or 1
        line_end = request.line_end or 1
        if line_start > len(lines) or line_end > len(lines):
            return self._error(target, "line range is outside file")
        selected = lines[line_start - 1 : line_end]
        replacement = _line_replacement_text(request.replacement or "", selected)
        updated_content = "".join([*lines[: line_start - 1], replacement, *lines[line_end:]])
        return self._commit(target, source_content, updated_content)

    def _commit(
        self,
        target: Path,
        source_content: str,
        updated_content: str,
    ) -> ToolResult:
        expected_sha256 = content_sha256(source_content.encode("utf-8"))
        try:
            receipt = self._mutations.edit(target, expected_sha256, updated_content)
        except FileMutationError as exc:
            return self._error(target, str(exc))
        return _edit_success(receipt, source_content, updated_content)

    def _error(self, target: Path, message: str, **details: Any) -> ToolResult:
        canonical_path = relative_to_root(self.project_root, target)
        return ToolResult(
            content=message,
            is_error=True,
            effects=(
                tool_effect(
                    "file.edit",
                    EFFECT_NONE,
                    status=STATUS_ERROR,
                    target_type="file",
                    target=canonical_path,
                    name=self.name,
                    **details,
                ),
            ),
        )


def _edit_success(
    receipt: FileMutationReceipt,
    source_content: str,
    updated_content: str,
) -> ToolResult:
    receipt_payload = receipt.to_dict()
    return ToolResult(
        content=(
            f"Edited {receipt.canonical_path}\n"
            f"{_diff(receipt.canonical_path, source_content, updated_content)}"
        ),
        metadata={"file_mutation": receipt_payload},
        effects=(
            tool_effect(
                receipt.operation,
                FILE_WRITTEN,
                target_type="file",
                target=receipt.canonical_path,
                name="edit_file",
                file_mutation=receipt_payload,
            ),
        ),
    )


def _line_replacement_text(replacement: str, selected: list[str]) -> str:
    if not replacement:
        return replacement
    selected_ended_with_newline = bool(selected and selected[-1].endswith("\n"))
    if selected_ended_with_newline and not replacement.endswith("\n"):
        return replacement + "\n"
    return replacement


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
