from __future__ import annotations

from typing import TYPE_CHECKING

from src.tools.builtin.path_utils import resolve_file_resource
from src.tools.effects import ResourceRef, tool_effect

if TYPE_CHECKING:
    from pathlib import Path


def test_file_resource_resolves_unique_basename_alias(tmp_path: Path) -> None:
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "TODO.md").write_text("todo", encoding="utf-8")

    resource = resolve_file_resource(tmp_path, "TODO.md")

    assert resource == ResourceRef(kind="file", canonical="data/TODO.md", raw="TODO.md")


def test_file_resource_reports_ambiguous_basename_alias(tmp_path: Path) -> None:
    (tmp_path / "data").mkdir()
    (tmp_path / "docs").mkdir()
    (tmp_path / "data" / "TODO.md").write_text("data", encoding="utf-8")
    (tmp_path / "docs" / "TODO.md").write_text("docs", encoding="utf-8")

    resource = resolve_file_resource(tmp_path, "TODO.md")

    assert resource.kind == "file"
    assert resource.raw == "TODO.md"
    assert resource.canonical == ""
    assert resource.error == "ambiguous_resource"
    assert resource.ambiguity == ("data/TODO.md", "docs/TODO.md")


def test_file_resource_normalizes_absolute_and_relative_paths(tmp_path: Path) -> None:
    (tmp_path / "data").mkdir()
    target = tmp_path / "data" / "TODO.md"
    target.write_text("todo", encoding="utf-8")

    relative = resolve_file_resource(tmp_path, "./data/../data/TODO.md")
    absolute = resolve_file_resource(tmp_path, str(target))

    assert relative.canonical == "data/TODO.md"
    assert absolute.canonical == "data/TODO.md"


def test_file_resource_rejects_project_root_escape(tmp_path: Path) -> None:
    resource = resolve_file_resource(tmp_path, "../outside.md")

    assert resource.kind == "file"
    assert resource.raw == "../outside.md"
    assert resource.error == "outside_project_root"


def test_tool_effect_serializes_resource_reference() -> None:
    effect = tool_effect(
        "file.write",
        "file_written",
        target_type="file",
        target="notes/example.md",
    )

    assert effect.resource == ResourceRef(
        kind="file",
        canonical="notes/example.md",
        raw="notes/example.md",
    )
    assert effect.to_dict()["resource"] == {
        "kind": "file",
        "canonical": "notes/example.md",
        "raw": "notes/example.md",
    }
