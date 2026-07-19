"""Read-only workspace file inspection tool."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from src.tools.effects import EFFECT_NONE, STATUS_COMPLETED, STATUS_ERROR, tool_effect
from src.tools.file_mutation_receipt import content_sha256
from src.tools.registry import ToolResult

if TYPE_CHECKING:
    from src.tools.effects import ToolEffect

DEFAULT_PROJECT_ROOT = Path(".")
EFFECT_FILE_READ = "file_read"
EFFECT_FILE_LISTED = "file_listed"
EFFECT_FILE_INSPECTED = "file_inspected"


class FileManagerTool:
    """Read and inspect files within the project root."""

    def __init__(self, root: Path | None = None) -> None:
        self._root = root or DEFAULT_PROJECT_ROOT

    @property
    def project_root(self) -> Path:
        """Return the resolved project root."""
        return self._root.resolve()

    @property
    def name(self) -> str:
        return "file_manager"

    @property
    def project_root_text(self) -> str:
        """Return the resolved project root as a string."""
        return str(self.project_root)

    @property
    def description(self) -> str:
        return (
            "Reads files, reports file hashes, and lists directories under project root "
            f"{self.project_root_text}. Use when inspecting files or obtaining the current "
            "SHA-256 required by replace_file. Do not use when modifying files; use "
            "create_file, append_file, edit_file, or replace_file instead."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": ["read_file", "inspect_file", "list_directory"],
                    "description": "The read-only file operation to perform",
                },
                "path": {
                    "type": "string",
                    "description": (
                        "Relative path within project root "
                        f"{self.project_root_text} (default: '.' for list)"
                    ),
                    "default": ".",
                },
            },
            "required": ["operation"],
        }

    @property
    def category(self) -> str:
        return "filesystem"

    def _resolve_safe_path(self, relative: str) -> Path | None:
        """Resolve path and verify it stays within project root."""
        project_root = self.project_root
        try:
            target = (project_root / relative).resolve()
        except (OSError, RuntimeError):
            return None
        return target if target.is_relative_to(project_root) else None

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        operation = args.get("operation", "")
        operations = {
            "read_file": self._read_file,
            "inspect_file": self._inspect_file,
            "list_directory": self._list_directory,
        }
        file_operation = operations.get(operation)
        if not file_operation:
            return ToolResult(
                content=(
                    f"Unknown operation: {operation}. Use: read_file, inspect_file, list_directory"
                ),
                is_error=True,
            )
        return file_operation(args)

    def _read_file(self, args: dict[str, Any]) -> ToolResult:
        path = args.get("path", "")
        target, path_error = self._existing_file(path, action="file.read")
        if path_error is not None:
            return path_error
        assert target is not None
        try:
            file_content = target.read_bytes()
            content = file_content.decode("utf-8")
        except UnicodeDecodeError:
            return self._file_error(
                f"Cannot read binary file: {path}",
                action="file.read",
                path=path,
            )
        except OSError as exc:
            return self._file_error(f"Read failed: {exc}", action="file.read", path=path)
        return ToolResult(
            content=content,
            metadata={"size": len(file_content)},
            effects=(self._file_effect("file.read", EFFECT_FILE_READ, path=path),),
        )

    def _inspect_file(self, args: dict[str, Any]) -> ToolResult:
        path = args.get("path", "")
        target, path_error = self._existing_file(path, action="file.inspect")
        if path_error is not None:
            return path_error
        assert target is not None
        try:
            file_content = target.read_bytes()
        except OSError as exc:
            return self._file_error(f"Inspect failed: {exc}", action="file.inspect", path=path)
        sha256 = content_sha256(file_content)
        canonical_path = target.relative_to(self.project_root).as_posix()
        return ToolResult(
            content=f"Path: {canonical_path}\nSize: {len(file_content)} bytes\nSHA-256: {sha256}",
            metadata={"path": canonical_path, "size": len(file_content), "sha256": sha256},
            effects=(self._file_effect("file.inspect", EFFECT_FILE_INSPECTED, path=path),),
        )

    def _existing_file(
        self,
        path: str,
        *,
        action: str,
    ) -> tuple[Path | None, ToolResult | None]:
        if not path:
            return None, self._file_error("Path is required", action=action, path=path)
        target = self._resolve_safe_path(path)
        if target is None:
            return None, self._file_error(
                "Invalid path: outside project root",
                action=action,
                path=path,
            )
        if target.is_dir():
            return None, self._file_error(
                f"Path is a directory: {path}. Use list_directory to inspect it.",
                action=action,
                path=path,
            )
        if not target.is_file():
            return None, self._file_error(f"File not found: {path}", action=action, path=path)
        return target, None

    def _list_directory(self, args: dict[str, Any]) -> ToolResult:
        path = args.get("path", ".")
        target = self._resolve_safe_path(path)
        if target is None:
            return self._file_error(
                "Invalid path: outside project root",
                action="file.list",
                path=path,
            )
        if not target.is_dir():
            return self._file_error(
                f"Not a directory: {path}",
                action="file.list",
                path=path,
            )
        try:
            lines = _directory_lines(target, self.project_root)
        except OSError as exc:
            return self._file_error(f"List failed: {exc}", action="file.list", path=path)
        return _directory_listing(
            path,
            self.project_root_text,
            lines,
            root=self.project_root,
        )

    def _file_error(self, message: str, *, action: str, path: str) -> ToolResult:
        return ToolResult(
            content=message,
            is_error=True,
            effects=(
                self._file_effect(
                    action,
                    EFFECT_NONE,
                    path=path,
                    status=STATUS_ERROR,
                ),
            ),
        )

    def _file_effect(
        self,
        action: str,
        effect: str,
        *,
        path: str,
        status: str = STATUS_COMPLETED,
    ) -> ToolEffect:
        canonical_path = _canonical_path(path, self.project_root)
        return tool_effect(
            action,
            effect,
            status=status,
            target_type="file",
            target=canonical_path,
            name=self.name,
        )


def _directory_lines(target: Path, project_root: Path) -> list[str]:
    entries = sorted(target.iterdir(), key=lambda path: (not path.is_dir(), path.name))
    lines: list[str] = []
    for entry in entries:
        relative_path = entry.relative_to(project_root)
        suffix = "/" if entry.is_dir() else f"  ({entry.stat().st_size} bytes)"
        lines.append(f"  {relative_path}{suffix}")
    return lines


def _directory_listing(
    path: str,
    project_root_text: str,
    lines: list[str],
    *,
    root: Path,
) -> ToolResult:
    header = f"Project root: {project_root_text}\nPath: {path}\n"
    content = header + ("\n".join(lines) if lines else "(empty directory)")
    return ToolResult(
        content=content,
        metadata={"path": path, "count": len(lines), "project_root": project_root_text},
        effects=(
            tool_effect(
                "file.list",
                EFFECT_FILE_LISTED,
                target_type="file",
                target=_canonical_path(path, root),
                name="file_manager",
            ),
        ),
    )


def _canonical_path(path: str, root: Path) -> str:
    try:
        target = (root / path).resolve()
    except (OSError, RuntimeError):
        return path
    if not target.is_relative_to(root):
        return path
    return target.relative_to(root).as_posix()
