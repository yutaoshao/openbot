"""Workspace file management tool."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.tools.registry import ToolResult

# Workspace root for file operations (project data directory)
DEFAULT_WORKSPACE = Path("data/workspace")
# Safety: maximum file size to read
MAX_READ_SIZE = 50000
# Safety: maximum file size to write
MAX_WRITE_SIZE = 50000


class FileManagerTool:
    """Manage files within the workspace directory."""

    def __init__(self, workspace: Path | None = None) -> None:
        self._workspace = workspace or DEFAULT_WORKSPACE

    @property
    def workspace(self) -> Path:
        """Ensure workspace exists and return it."""
        self._workspace.mkdir(parents=True, exist_ok=True)
        return self._workspace.resolve()

    @property
    def name(self) -> str:
        return "file_manager"

    @property
    def description(self) -> str:
        return (
            "Read, write, and list files in the workspace. "
            "Supports operations: read_file, write_file, list_directory. "
            "All paths are relative to the workspace root."
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
                    "description": "Relative path within workspace (default: '.' for list)",
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
        """Resolve path and verify it stays within workspace.

        Returns None if path traversal is detected.
        """
        try:
            target = (self.workspace / relative).resolve()
            # Prevent path traversal outside workspace
            if not str(target).startswith(str(self.workspace)):
                return None
            return target
        except (ValueError, OSError):
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
            return ToolResult(content="Path is required for read_file", is_error=True)

        target = self._resolve_safe_path(path)
        if target is None:
            return ToolResult(content="Invalid path: outside workspace boundary", is_error=True)

        if not target.is_file():
            return ToolResult(content=f"File not found: {path}", is_error=True)

        size = target.stat().st_size
        if size > MAX_READ_SIZE:
            return ToolResult(
                content=f"File too large: {size} bytes (max: {MAX_READ_SIZE})",
                is_error=True,
            )

        try:
            content = target.read_text(encoding="utf-8")
            return ToolResult(
                content=content,
                metadata={"path": path, "size": size},
            )
        except UnicodeDecodeError:
            return ToolResult(content=f"Cannot read binary file: {path}", is_error=True)

    def _write_file(self, args: dict[str, Any]) -> ToolResult:
        path = args.get("path", "")
        content = args.get("content", "")

        if not path:
            return ToolResult(content="Path is required for write_file", is_error=True)

        if len(content) > MAX_WRITE_SIZE:
            return ToolResult(
                content=f"Content too large: {len(content)} chars (max: {MAX_WRITE_SIZE})",
                is_error=True,
            )

        target = self._resolve_safe_path(path)
        if target is None:
            return ToolResult(content="Invalid path: outside workspace boundary", is_error=True)

        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            return ToolResult(
                content=f"Written {len(content)} chars to {path}",
                metadata={"path": path, "size": len(content)},
            )
        except OSError as e:
            return ToolResult(content=f"Write failed: {e}", is_error=True)

    def _list_directory(self, args: dict[str, Any]) -> ToolResult:
        path = args.get("path", ".")

        target = self._resolve_safe_path(path)
        if target is None:
            return ToolResult(content="Invalid path: outside workspace boundary", is_error=True)

        if not target.is_dir():
            return ToolResult(content=f"Not a directory: {path}", is_error=True)

        try:
            entries = sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name))
            lines = []
            for entry in entries:
                rel = entry.relative_to(self.workspace)
                suffix = "/" if entry.is_dir() else f"  ({entry.stat().st_size} bytes)"
                lines.append(f"  {rel}{suffix}")

            if not lines:
                return ToolResult(content="(empty directory)", metadata={"path": path})

            header = f"Workspace: {path}\n"
            return ToolResult(
                content=header + "\n".join(lines),
                metadata={"path": path, "count": len(lines)},
            )
        except OSError as e:
            return ToolResult(content=f"List failed: {e}", is_error=True)
