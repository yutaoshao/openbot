from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest

from src.tools.builtin.file_mutation_tools import (
    AppendFileTool,
    CreateFileTool,
    ReplaceFileTool,
)
from src.tools.effects import tool_effect
from src.tools.file_mutation_receipt import (
    FILE_WRITTEN,
    content_sha256,
    verified_file_mutation,
)
from src.tools.file_mutation_service import FileMutationError, FileMutationService

if TYPE_CHECKING:
    from pathlib import Path


async def test_create_file_never_overwrites_an_existing_target(tmp_path: Path) -> None:
    service = FileMutationService(tmp_path)
    tool = CreateFileTool(service)

    created = await tool.execute({"path": "notes.md", "content": "original\n"})
    rejected = await tool.execute({"path": "notes.md", "content": "replacement\n"})

    assert not created.is_error
    assert verified_file_mutation(created.effects[0], tmp_path)
    assert created.effects[0].details["file_mutation"]["snapshot_path"] == ""
    assert rejected.is_error
    assert "already exists" in rejected.content
    assert (tmp_path / "notes.md").read_text(encoding="utf-8") == "original\n"


async def test_append_preserves_large_prefix_and_snapshots_source(tmp_path: Path) -> None:
    target = tmp_path / "AI 八股.md"
    original = "".join(f"line {line_number}\n" for line_number in range(500))
    target.write_text(original, encoding="utf-8")
    tool = AppendFileTool(FileMutationService(tmp_path))

    appended = await tool.execute({"path": "AI 八股.md", "content": "new section\n"})

    assert not appended.is_error
    assert target.read_text(encoding="utf-8") == original + "new section\n"
    receipt = appended.effects[0].details["file_mutation"]
    assert (tmp_path / receipt["snapshot_path"]).read_text(encoding="utf-8") == original
    assert receipt["appended_sha256"] == content_sha256(b"new section\n")
    assert verified_file_mutation(appended.effects[0], tmp_path)


async def test_replace_requires_current_hash_and_preserves_failed_source(
    tmp_path: Path,
) -> None:
    target = tmp_path / "notes.md"
    target.write_text("original\n", encoding="utf-8")
    tool = ReplaceFileTool(FileMutationService(tmp_path))

    rejected = await tool.execute(
        {"path": "notes.md", "expected_sha256": "0" * 64, "content": "wrong\n"}
    )

    assert rejected.is_error
    assert "changed since it was read" in rejected.content
    assert target.read_text(encoding="utf-8") == "original\n"
    assert not (tmp_path / "data/file_snapshots").exists()

    current_hash = content_sha256(target.read_bytes())
    replaced = await tool.execute(
        {"path": "notes.md", "expected_sha256": current_hash, "content": "replacement\n"}
    )

    assert not replaced.is_error
    assert target.read_text(encoding="utf-8") == "replacement\n"
    assert verified_file_mutation(replaced.effects[0], tmp_path)
    snapshot_path = replaced.effects[0].details["file_mutation"]["snapshot_path"]
    assert (tmp_path / snapshot_path).read_text(encoding="utf-8") == "original\n"

    unchanged = await tool.execute(
        {
            "path": "notes.md",
            "expected_sha256": content_sha256(target.read_bytes()),
            "content": "replacement\n",
        }
    )
    assert unchanged.is_error
    assert "would not change file content" in unchanged.content


async def test_same_file_appends_are_serialized_without_lost_content(tmp_path: Path) -> None:
    target = tmp_path / "notes.md"
    target.write_text("base\n", encoding="utf-8")
    service = FileMutationService(tmp_path)

    receipts = await asyncio.gather(
        asyncio.to_thread(service.append, target, "first\n"),
        asyncio.to_thread(service.append, target, "second\n"),
    )

    assert target.read_text(encoding="utf-8") in {
        "base\nfirst\nsecond\n",
        "base\nsecond\nfirst\n",
    }
    assert all((tmp_path / receipt.snapshot_path).is_file() for receipt in receipts)
    effects = tuple(
        tool_effect(
            receipt.operation,
            FILE_WRITTEN,
            target_type="file",
            target=receipt.canonical_path,
            file_mutation=receipt.to_dict(),
        )
        for receipt in receipts
    )
    assert sum(verified_file_mutation(effect, tmp_path) for effect in effects) == 1


def test_atomic_replace_failure_leaves_original_content(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "notes.md"
    target.write_text("original\n", encoding="utf-8")
    service = FileMutationService(tmp_path)

    def reject_replace(_source: Path, _target: Path) -> None:
        raise OSError("replace unavailable")

    monkeypatch.setattr("src.tools.file_mutation_service.os.replace", reject_replace)

    with pytest.raises(FileMutationError, match="Atomic replace failed"):
        service.append(target, "new\n")

    assert target.read_text(encoding="utf-8") == "original\n"
    assert not tuple(tmp_path.glob(".notes.md.*.tmp"))


async def test_receipt_fails_after_target_is_modified_out_of_band(tmp_path: Path) -> None:
    target = tmp_path / "notes.md"
    created = await CreateFileTool(FileMutationService(tmp_path)).execute(
        {"path": "notes.md", "content": "verified\n"}
    )
    assert verified_file_mutation(created.effects[0], tmp_path)

    target.write_text("tampered\n", encoding="utf-8")

    assert not verified_file_mutation(created.effects[0], tmp_path)


def test_mutation_service_rejects_targets_outside_project_root(tmp_path: Path) -> None:
    service = FileMutationService(tmp_path / "workspace")
    outside = tmp_path / "outside.md"

    with pytest.raises(FileMutationError, match="outside project root"):
        service.create(outside, "blocked\n")

    assert not outside.exists()
