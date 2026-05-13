"""Workspace file management tool."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.tools.registry import ToolResult

# Project root for file operations
DEFAULT_PROJECT_ROOT = Path(".")
STATUS_COMPLETED = "completed"
STATUS_ERROR = "error"
EFFECT_NONE = "none"
EFFECT_READ = "read"
EFFECT_WRITTEN = "written"


class FileManagerTool:
    """Manage files within the project root."""

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
            f"Reads, writes, and lists complete files under project root {self.project_root_text}. "
            "Use when the task involves project files, runtime data files, skill reference "
            "files, or saved tool outputs relative to that project root. "
            "Do not use when the path is outside the project root, the file is binary, "
            "or the task needs shell commands, codebase-wide search, or incremental edits."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": ["read_file", "write_file", "list_directory"],
                    "description": "The file operation to perform",
                },
                "path": {
                    "type": "string",
                    "description": (
                        "Relative path within project root "
                        f"{self.project_root_text} (default: '.' for list)"
                    ),
                    "default": ".",
                },
                "content": {
                    "type": "string",
                    "description": "Content to write (required for write_file)",
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
            if not target.is_relative_to(project_root):
                return None
            return target
        except (OSError, RuntimeError):
            return None

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        operation = args.get("operation", "")

        dispatch = {
            "read_file": self._read_file,
            "write_file": self._write_file,
            "list_directory": self._list_directory,
        }

        handler = dispatch.get(operation)
        if not handler:
            return ToolResult(
                content=f"Unknown operation: {operation}. "
                "Use: read_file, write_file, list_directory",
                is_error=True,
            )

        return handler(args)

    def _read_file(self, args: dict[str, Any]) -> ToolResult:
        path = args.get("path", "")
        if not path:
            return ToolResult(
                content="Path is required for read_file",
                is_error=True,
                metadata=_metadata("read_file", path, STATUS_ERROR, EFFECT_NONE),
            )

        target = self._resolve_safe_path(path)
        if target is None:
            return ToolResult(
                content="Invalid path: outside project root",
                is_error=True,
                metadata=_metadata("read_file", path, STATUS_ERROR, EFFECT_NONE),
            )

        if target.is_dir():
            return ToolResult(
                content=(
                    f"Path is a directory: {path}. Use list_directory to inspect it, "
                    "or read_file with a concrete file path."
                ),
                is_error=True,
                metadata=_metadata("read_file", path, STATUS_ERROR, EFFECT_NONE),
            )

        if not target.is_file():
            return ToolResult(
                content=f"File not found: {path}",
                is_error=True,
                metadata=_metadata("read_file", path, STATUS_ERROR, EFFECT_NONE),
            )

        try:
            size = target.stat().st_size
            content = target.read_text(encoding="utf-8")
            return ToolResult(
                content=content,
                metadata={
                    **_metadata("read_file", path, STATUS_COMPLETED, EFFECT_READ),
                    "size": size,
                },
            )
        except UnicodeDecodeError:
            return ToolResult(
                content=f"Cannot read binary file: {path}",
                is_error=True,
                metadata=_metadata("read_file", path, STATUS_ERROR, EFFECT_NONE),
            )

    def _write_file(self, args: dict[str, Any]) -> ToolResult:
        path = args.get("path", "")
        content = args.get("content", "")

        if not path:
            return ToolResult(
                content="Path is required for write_file",
                is_error=True,
                metadata=_metadata("write_file", path, STATUS_ERROR, EFFECT_NONE),
            )

        target = self._resolve_safe_path(path)
        if target is None:
            return ToolResult(
                content="Invalid path: outside project root",
                is_error=True,
                metadata=_metadata("write_file", path, STATUS_ERROR, EFFECT_NONE),
            )

        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            return ToolResult(
                content=f"Written {len(content)} chars to {path}",
                metadata={
                    **_metadata("write_file", path, STATUS_COMPLETED, EFFECT_WRITTEN),
                    "size": len(content),
                },
            )
        except OSError as e:
            return ToolResult(
                content=f"Write failed: {e}",
                is_error=True,
                metadata=_metadata("write_file", path, STATUS_ERROR, EFFECT_NONE),
            )

    def _list_directory(self, args: dict[str, Any]) -> ToolResult:
        path = args.get("path", ".")

        target = self._resolve_safe_path(path)
        if target is None:
            return ToolResult(content="Invalid path: outside project root", is_error=True)

        if not target.is_dir():
            return ToolResult(content=f"Not a directory: {path}", is_error=True)

        try:
            entries = sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name))
            lines = []
            for entry in entries:
                rel = entry.relative_to(self.project_root)
                suffix = "/" if entry.is_dir() else f"  ({entry.stat().st_size} bytes)"
                lines.append(f"  {rel}{suffix}")

            if not lines:
                return ToolResult(
                    content=(
                        f"Project root: {self.project_root_text}\nPath: {path}\n(empty directory)"
                    ),
                    metadata={"path": path, "project_root": self.project_root_text},
                )

            header = f"Project root: {self.project_root_text}\nPath: {path}\n"
            return ToolResult(
                content=header + "\n".join(lines),
                metadata={
                    "path": path,
                    "count": len(lines),
                    "project_root": self.project_root_text,
                },
            )
        except OSError as e:
            return ToolResult(content=f"List failed: {e}", is_error=True)


def _metadata(operation: str, path: str, status: str, effect: str) -> dict[str, Any]:
    return {
        "operation": operation,
        "path": path,
        "status": status,
        "effect": effect,
    }
