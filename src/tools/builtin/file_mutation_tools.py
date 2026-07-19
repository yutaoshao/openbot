"""Explicit create, append, and replace tools for UTF-8 text files."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import Field

from src.tools.builtin.path_utils import relative_to_root, resolve_project_path
from src.tools.builtin.validation import StrictToolInput, schema_for, validate_args
from src.tools.effects import EFFECT_NONE, STATUS_ERROR, tool_effect
from src.tools.file_mutation_receipt import FILE_WRITTEN, FileMutationReceipt
from src.tools.file_mutation_service import FileMutationError, FileMutationService
from src.tools.registry import ToolResult

SHA256_PATTERN = r"^[0-9a-f]{64}$"

if TYPE_CHECKING:
    from pathlib import Path


class CreateFileInput(StrictToolInput):
    path: str = Field(min_length=1)
    content: str


class AppendFileInput(StrictToolInput):
    path: str = Field(min_length=1)
    content: str = Field(min_length=1)


class ReplaceFileInput(StrictToolInput):
    path: str = Field(min_length=1)
    expected_sha256: str = Field(pattern=SHA256_PATTERN)
    content: str


class CreateFileTool:
    """Create new text files without overwriting existing paths."""

    def __init__(self, mutation_service: FileMutationService) -> None:
        self._mutations = mutation_service

    @property
    def project_root(self) -> Path:
        return self._mutations.project_root

    @property
    def name(self) -> str:
        return "create_file"

    @property
    def description(self) -> str:
        return (
            f"Creates a new UTF-8 text file under project root {self.project_root}. "
            "Use when the target must not already exist. "
            "Do not use when appending, editing, or replacing an existing file."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return schema_for(CreateFileInput)

    @property
    def category(self) -> str:
        return "filesystem"

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        request, validation_error = validate_args(CreateFileInput, args, tool_name=self.name)
        if validation_error is not None:
            return validation_error
        assert request is not None
        target, path_error = resolve_project_path(
            self.project_root,
            request.path,
            operation=self.name,
        )
        if path_error is not None:
            return path_error
        assert target is not None
        try:
            receipt = self._mutations.create(target, request.content)
        except FileMutationError as exc:
            return _mutation_error(
                self.name,
                receipt_action="file.create",
                canonical_path=relative_to_root(self.project_root, target),
                message=str(exc),
            )
        return _mutation_success(self.name, receipt, f"Created {receipt.canonical_path}")


class AppendFileTool:
    """Append text while preserving every existing byte."""

    def __init__(self, mutation_service: FileMutationService) -> None:
        self._mutations = mutation_service

    @property
    def project_root(self) -> Path:
        return self._mutations.project_root

    @property
    def name(self) -> str:
        return "append_file"

    @property
    def description(self) -> str:
        return (
            f"Appends UTF-8 text to an existing file under project root {self.project_root}. "
            "Use when adding notes or sections without changing existing content. "
            "Do not use when Bash redirection or whole-file replacement would be required."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return schema_for(AppendFileInput)

    @property
    def category(self) -> str:
        return "filesystem"

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        request, validation_error = validate_args(AppendFileInput, args, tool_name=self.name)
        if validation_error is not None:
            return validation_error
        assert request is not None
        target, path_error = resolve_project_path(
            self.project_root,
            request.path,
            operation=self.name,
        )
        if path_error is not None:
            return path_error
        assert target is not None
        try:
            receipt = self._mutations.append(target, request.content)
        except FileMutationError as exc:
            return _mutation_error(
                self.name,
                receipt_action="file.append",
                canonical_path=relative_to_root(self.project_root, target),
                message=str(exc),
            )
        return _mutation_success(self.name, receipt, f"Appended {receipt.canonical_path}")


class ReplaceFileTool:
    """Replace complete text files with an optimistic concurrency precondition."""

    def __init__(self, mutation_service: FileMutationService) -> None:
        self._mutations = mutation_service

    @property
    def project_root(self) -> Path:
        return self._mutations.project_root

    @property
    def name(self) -> str:
        return "replace_file"

    @property
    def description(self) -> str:
        return (
            f"Replaces an existing UTF-8 text file under project root {self.project_root}. "
            "Use when an intentional whole-file replacement is required after inspecting its "
            "SHA-256. "
            "Do not use when a targeted edit or append can preserve unrelated content."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return schema_for(ReplaceFileInput)

    @property
    def category(self) -> str:
        return "filesystem"

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        request, validation_error = validate_args(ReplaceFileInput, args, tool_name=self.name)
        if validation_error is not None:
            return validation_error
        assert request is not None
        target, path_error = resolve_project_path(
            self.project_root,
            request.path,
            operation=self.name,
        )
        if path_error is not None:
            return path_error
        assert target is not None
        try:
            receipt = self._mutations.replace(target, request.expected_sha256, request.content)
        except FileMutationError as exc:
            return _mutation_error(
                self.name,
                receipt_action="file.replace",
                canonical_path=relative_to_root(self.project_root, target),
                message=str(exc),
            )
        return _mutation_success(self.name, receipt, f"Replaced {receipt.canonical_path}")


def _mutation_success(
    tool_name: str,
    receipt: FileMutationReceipt,
    message: str,
) -> ToolResult:
    receipt_payload = receipt.to_dict()
    return ToolResult(
        content=message,
        metadata={"file_mutation": receipt_payload},
        effects=(
            tool_effect(
                receipt.operation,
                FILE_WRITTEN,
                target_type="file",
                target=receipt.canonical_path,
                name=tool_name,
                file_mutation=receipt_payload,
            ),
        ),
    )


def _mutation_error(
    tool_name: str,
    *,
    receipt_action: str,
    canonical_path: str,
    message: str,
) -> ToolResult:
    return ToolResult(
        content=message,
        is_error=True,
        effects=(
            tool_effect(
                receipt_action,
                EFFECT_NONE,
                status=STATUS_ERROR,
                target_type="file",
                target=canonical_path,
                name=tool_name,
            ),
        ),
    )
