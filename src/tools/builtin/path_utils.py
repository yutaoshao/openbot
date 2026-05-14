"""Project-root path helpers for filesystem tools."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.tools.registry import ToolResult

DEFAULT_PROJECT_ROOT = Path(".")
STATUS_ERROR = "error"
EFFECT_NONE = "none"


def project_root(root: Path | None) -> Path:
    """Resolve the configured project root."""
    return (root or DEFAULT_PROJECT_ROOT).resolve()


def resolve_project_path(
    root: Path | None,
    path: str,
    *,
    operation: str,
) -> tuple[Path | None, ToolResult | None]:
    """Resolve *path* and require it to stay under the project root."""
    base = project_root(root)
    try:
        target = _candidate_path(base, path).resolve()
    except (OSError, RuntimeError) as exc:
        return None, _path_error(operation, path, f"Invalid path: {exc}")

    if not target.is_relative_to(base):
        return None, _path_error(operation, path, "Invalid path: outside project root")
    return target, None


def relative_to_root(root: Path | None, target: Path) -> str:
    """Return a POSIX path relative to the configured project root."""
    return target.resolve().relative_to(project_root(root)).as_posix()


def _candidate_path(root: Path, path: str) -> Path:
    candidate = Path(path).expanduser()
    if candidate.is_absolute():
        return candidate
    return root / candidate


def _path_error(operation: str, path: str, content: str) -> ToolResult:
    return ToolResult(
        content=content,
        is_error=True,
        metadata=_metadata(operation, path, STATUS_ERROR, EFFECT_NONE),
    )


def _metadata(
    operation: str,
    path: str,
    status: str,
    effect: str,
    **extra: Any,
) -> dict[str, Any]:
    return {
        "operation": operation,
        "path": path,
        "status": status,
        "effect": effect,
        **extra,
    }
