from __future__ import annotations

from typing import TYPE_CHECKING

from src.tools.builtin.edit_file import EditFileTool
from src.tools.builtin.glob_tool import GlobTool
from src.tools.builtin.grep_tool import GrepTool

if TYPE_CHECKING:
    from pathlib import Path


async def test_edit_file_rejects_unknown_arguments(tmp_path: Path) -> None:
    tool = EditFileTool(root=tmp_path)

    result = await tool.execute({"file_path": "notes.txt", "unexpected": "value"})

    assert result.is_error
    assert "Invalid arguments for edit_file" in result.content
    assert result.effects[0].status == "validation_error"
    assert result.metadata["validation_errors"][0]["loc"] == ("unexpected",)


async def test_edit_file_replaces_exact_old_text_once(tmp_path: Path) -> None:
    target = tmp_path / "sample.txt"
    target.write_text("one\nneedle\nthree\n", encoding="utf-8")
    tool = EditFileTool(root=tmp_path)

    result = await tool.execute(
        {
            "file_path": "sample.txt",
            "old_text": "needle",
            "new_text": "changed",
        }
    )

    assert not result.is_error
    assert target.read_text(encoding="utf-8") == "one\nchanged\nthree\n"
    assert result.effects[0].effect == "file_written"
    assert result.effects[0].details["mode"] == "old_text"
    assert result.effects[0].target == "sample.txt"
    assert "-needle" in result.content
    assert "+changed" in result.content


async def test_edit_file_reports_missing_old_text_without_writing(tmp_path: Path) -> None:
    target = tmp_path / "sample.txt"
    original = "one\ntwo\n"
    target.write_text(original, encoding="utf-8")
    tool = EditFileTool(root=tmp_path)

    result = await tool.execute(
        {
            "file_path": "sample.txt",
            "old_text": "missing",
            "new_text": "changed",
        }
    )

    assert result.is_error
    assert "old_text not found" in result.content
    assert target.read_text(encoding="utf-8") == original
    assert result.effects[0].effect == "none"


async def test_edit_file_reports_multiple_old_text_matches(tmp_path: Path) -> None:
    target = tmp_path / "sample.txt"
    original = "needle\nneedle\n"
    target.write_text(original, encoding="utf-8")
    tool = EditFileTool(root=tmp_path)

    result = await tool.execute(
        {
            "file_path": "sample.txt",
            "old_text": "needle",
            "new_text": "changed",
        }
    )

    assert result.is_error
    assert "old_text matched 2 times" in result.content
    assert target.read_text(encoding="utf-8") == original
    assert result.effects[0].details["match_count"] == 2


async def test_edit_file_replaces_inclusive_line_range(tmp_path: Path) -> None:
    target = tmp_path / "sample.txt"
    target.write_text("alpha\nbeta\ngamma\ndelta\n", encoding="utf-8")
    tool = EditFileTool(root=tmp_path)

    result = await tool.execute(
        {
            "file_path": "sample.txt",
            "line_start": 2,
            "line_end": 3,
            "replacement": "BETA\nGAMMA",
        }
    )

    assert not result.is_error
    assert target.read_text(encoding="utf-8") == "alpha\nBETA\nGAMMA\ndelta\n"
    assert result.effects[0].details["mode"] == "line_range"
    assert result.effects[0].details["line_start"] == 2
    assert result.effects[0].details["line_end"] == 3


async def test_edit_file_rejects_directory_binary_and_path_escape(tmp_path: Path) -> None:
    (tmp_path / "dir").mkdir()
    (tmp_path / "binary.bin").write_bytes(b"\xff\xfe\x00")
    tool = EditFileTool(root=tmp_path)

    directory = await tool.execute({"file_path": "dir", "old_text": "x", "new_text": "y"})
    binary = await tool.execute({"file_path": "binary.bin", "old_text": "x", "new_text": "y"})
    escaped = await tool.execute({"file_path": "../escape.txt", "old_text": "x", "new_text": "y"})

    assert directory.is_error
    assert "Path is a directory" in directory.content
    assert binary.is_error
    assert "Cannot edit binary file" in binary.content
    assert escaped.is_error
    assert "outside project root" in escaped.content


async def test_glob_returns_matching_files_with_limit(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("print('a')\n", encoding="utf-8")
    (tmp_path / "src" / "b.py").write_text("print('b')\n", encoding="utf-8")
    (tmp_path / "src" / "c.txt").write_text("c\n", encoding="utf-8")
    tool = GlobTool(root=tmp_path)

    result = await tool.execute({"pattern": "src/*.py", "max_results": 1})

    assert not result.is_error
    assert result.content.splitlines() == ["src/a.py"]
    assert result.metadata["count"] == 1
    assert result.metadata["truncated"] is True


async def test_glob_reports_missing_ripgrep(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("src.tools.builtin.glob_tool.shutil.which", lambda _name: None)
    tool = GlobTool(root=tmp_path)

    result = await tool.execute({"pattern": "**/*.py"})

    assert result.is_error
    assert "ripgrep (rg) is required" in result.content
    assert result.effects[0].status == "missing_dependency"


async def test_grep_returns_matches_with_line_column_and_glob_filter(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("alpha\nneedle here\n", encoding="utf-8")
    (tmp_path / "src" / "b.txt").write_text("needle ignored\n", encoding="utf-8")
    tool = GrepTool(root=tmp_path)

    result = await tool.execute(
        {
            "pattern": "needle",
            "path": "src",
            "glob": "*.py",
            "max_results": 10,
        }
    )

    assert not result.is_error
    assert result.content.splitlines() == ["src/a.py:2:1:needle here"]
    assert result.metadata["count"] == 1
    assert result.metadata["truncated"] is False


async def test_grep_supports_literal_context_and_max_results(tmp_path: Path) -> None:
    target = tmp_path / "notes.txt"
    target.write_text("before\nneedle.*\nafter\nneedle.* again\n", encoding="utf-8")
    tool = GrepTool(root=tmp_path)

    result = await tool.execute(
        {
            "pattern": "needle.*",
            "literal": True,
            "context_lines": 1,
            "max_results": 1,
        }
    )

    assert not result.is_error
    lines = result.content.splitlines()
    assert lines == [
        "notes.txt:1:before",
        "notes.txt:2:1:needle.*",
        "notes.txt:3:after",
    ]
    assert result.metadata["count"] == 1
    assert result.metadata["truncated"] is True


async def test_grep_omits_context_for_truncated_matches(tmp_path: Path) -> None:
    target = tmp_path / "notes.txt"
    target.write_text(
        "first before\nneedle one\nfirst after\ngap one\ngap two\nsecond before\nneedle two\n",
        encoding="utf-8",
    )
    tool = GrepTool(root=tmp_path)

    result = await tool.execute(
        {
            "pattern": "needle",
            "context_lines": 1,
            "max_results": 1,
        }
    )

    assert not result.is_error
    assert result.content.splitlines() == [
        "notes.txt:1:first before",
        "notes.txt:2:1:needle one",
        "notes.txt:3:first after",
    ]
    assert result.metadata["count"] == 1
    assert result.metadata["truncated"] is True


async def test_grep_omits_adjacent_before_context_for_truncated_matches(tmp_path: Path) -> None:
    target = tmp_path / "notes.txt"
    target.write_text(
        "first before\nneedle one\nfirst after\nsecond before\nneedle two\n",
        encoding="utf-8",
    )
    tool = GrepTool(root=tmp_path)

    result = await tool.execute(
        {
            "pattern": "needle",
            "context_lines": 1,
            "max_results": 1,
        }
    )

    assert not result.is_error
    assert result.content.splitlines() == [
        "notes.txt:1:first before",
        "notes.txt:2:1:needle one",
        "notes.txt:3:first after",
    ]
    assert result.metadata["count"] == 1
    assert result.metadata["truncated"] is True
