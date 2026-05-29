from __future__ import annotations

from typing import TYPE_CHECKING

from src.tools.builtin.file_manager import FileManagerTool

if TYPE_CHECKING:
    from pathlib import Path


def test_file_manager_description_includes_project_root(tmp_path: Path) -> None:
    tool = FileManagerTool(root=tmp_path)

    assert str(tmp_path.resolve()) in tool.description


def test_list_directory_reports_project_root_for_empty_directory(tmp_path: Path) -> None:
    tool = FileManagerTool(root=tmp_path)

    result = tool._list_directory({"path": "."})

    assert not result.is_error
    assert f"Project root: {tmp_path.resolve()}" in result.content
    assert "Path: ." in result.content
    assert "(empty directory)" in result.content


def test_read_file_reports_directory_paths_explicitly(tmp_path: Path) -> None:
    (tmp_path / "src/agent/conversation").mkdir(parents=True)
    tool = FileManagerTool(root=tmp_path)

    result = tool._read_file({"path": "src/agent/conversation"})

    assert result.is_error
    assert "Path is a directory: src/agent/conversation" in result.content
    assert "list_directory" in result.content
    assert result.effects[0].status == "error"
    assert result.effects[0].action == "file.read"


async def test_write_file_reports_structured_write_effect(tmp_path: Path) -> None:
    tool = FileManagerTool(root=tmp_path)

    result = await tool.execute(
        {
            "operation": "write_file",
            "path": "notes/example.md",
            "content": "hello",
        }
    )

    assert not result.is_error
    assert result.effects[0].action == "file.write"
    assert result.effects[0].target == "notes/example.md"
    assert result.effects[0].effect == "file_written"
    assert result.effects[0].status == "completed"


def test_file_manager_reads_large_files_without_internal_truncation(tmp_path: Path) -> None:
    content = "x" * 12000
    (tmp_path / "large.txt").write_text(content, encoding="utf-8")
    tool = FileManagerTool(root=tmp_path)

    result = tool._read_file({"path": "large.txt"})

    assert not result.is_error
    assert result.content == content


def test_resolve_safe_path_rejects_prefix_bypass(tmp_path: Path) -> None:
    tool = FileManagerTool(root=tmp_path / "workspace")

    target = tool._resolve_safe_path("../workspace2/escape.txt")

    assert target is None


def test_resolve_safe_path_rejects_parent_escape(tmp_path: Path) -> None:
    tool = FileManagerTool(root=tmp_path / "workspace")

    target = tool._resolve_safe_path("../../etc/passwd")

    assert target is None
