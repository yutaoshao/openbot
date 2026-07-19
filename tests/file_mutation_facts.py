"""Real file-mutation facts shared by verification tests."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.tools.effects import ToolEffect, tool_effect
from src.tools.file_mutation_receipt import FILE_WRITTEN, FileMutationReceipt, content_sha256
from src.tools.file_mutation_service import FileMutationService

if TYPE_CHECKING:
    from pathlib import Path

_TOOL_BY_OPERATION = {
    "file.create": "create_file",
    "file.append": "append_file",
    "file.edit": "edit_file",
    "file.replace": "replace_file",
}


def created_file_effect(root: Path, relative_path: str, content: str = "verified\n") -> ToolEffect:
    """Create a real file and return its verified structured effect."""
    receipt = FileMutationService(root).create(root / relative_path, content)
    return effect_from_receipt(receipt)


def appended_file_effect(
    root: Path, relative_path: str, content: str = "\nverified\n"
) -> ToolEffect:
    """Append to a real file and return its verified structured effect."""
    receipt = FileMutationService(root).append(root / relative_path, content)
    return effect_from_receipt(receipt)


def edited_file_effect(root: Path, relative_path: str, updated_content: str) -> ToolEffect:
    """Edit a real existing file and return its verified structured effect."""
    target = root / relative_path
    source_content = target.read_bytes()
    receipt = FileMutationService(root).edit(
        target,
        content_sha256(source_content),
        updated_content,
    )
    return effect_from_receipt(receipt)


def effect_from_receipt(receipt: FileMutationReceipt) -> ToolEffect:
    """Convert a service receipt into the fact emitted by its structured tool."""
    receipt_payload = receipt.to_dict()
    return tool_effect(
        receipt.operation,
        FILE_WRITTEN,
        target_type="file",
        target=receipt.canonical_path,
        name=_TOOL_BY_OPERATION[receipt.operation],
        file_mutation=receipt_payload,
    )


def executed_mutation_call(effect: ToolEffect) -> dict[str, Any]:
    """Serialize a verified effect as one runtime tool-call record."""
    return {
        "name": effect.name,
        "is_error": False,
        "effects": [effect.to_dict()],
    }
