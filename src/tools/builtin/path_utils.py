"""Project-root path helpers for filesystem tools."""

from __future__ import annotations

from pathlib import Path

from src.tools.effects import EFFECT_NONE, STATUS_ERROR, ResourceRef, tool_effect
from src.tools.registry import ToolResult

DEFAULT_PROJECT_ROOT = Path(".")


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


def resolve_file_resource(root: Path | None, path: str) -> ResourceRef:
    """Resolve a user/tool file target to a canonical project-relative resource."""
    base = project_root(root)
    raw = path.strip()
    try:
        target = _candidate_path(base, raw).resolve()
    except (OSError, RuntimeError) as exc:
        return ResourceRef("file", "", raw, error=f"invalid_path:{exc}")
    if not target.is_relative_to(base):
        return ResourceRef("file", "", raw, error="outside_project_root")
    if target.exists() or _has_parent_or_suffix(raw):
        return ResourceRef("file", relative_to_root(base, target), raw)
    return _resolve_basename_alias(base, raw)


def _candidate_path(root: Path, path: str) -> Path:
    candidate = Path(path).expanduser()
    if candidate.is_absolute():
        return candidate
    return root / candidate


def _has_parent_or_suffix(path: str) -> bool:
    candidate = Path(path)
    return candidate.parent != Path(".") or path.endswith("/")


def _resolve_basename_alias(root: Path, raw: str) -> ResourceRef:
    matches = tuple(sorted(_matching_existing_paths(root, raw)))
    if not matches:
        return ResourceRef("file", raw, raw)
    if len(matches) == 1:
        return ResourceRef("file", matches[0], raw)
    return ResourceRef("file", "", raw, ambiguity=matches, error="ambiguous_resource")


def _matching_existing_paths(root: Path, name: str) -> tuple[str, ...]:
    return tuple(
        path.relative_to(root).as_posix()
        for path in root.rglob(name)
        if path.is_file() and _is_visible_match(path, root)
    )


def _is_visible_match(path: Path, root: Path) -> bool:
    return ".git" not in path.relative_to(root).parts


def _path_error(operation: str, path: str, content: str) -> ToolResult:
    return ToolResult(
        content=content,
        is_error=True,
        effects=(
            tool_effect(
                operation,
                EFFECT_NONE,
                status=STATUS_ERROR,
                target_type="file",
                target=path,
            ),
        ),
    )
