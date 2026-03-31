from __future__ import annotations

from pathlib import Path

from src.tools.builtin.file_manager import FileManagerTool


def test_file_manager_description_includes_workspace_root(tmp_path: Path) -> None:
    tool = FileManagerTool(workspace=tmp_path)

    assert str(tmp_path.resolve()) in tool.description


def test_list_directory_reports_workspace_root_for_empty_directory(tmp_path: Path) -> None:
    tool = FileManagerTool(workspace=tmp_path)

    result = tool._list_directory({"path": "."})

    assert not result.is_error
    assert f"Workspace root: {tmp_path.resolve()}" in result.content
    assert "Path: ." in result.content
    assert "(empty directory)" in result.content
