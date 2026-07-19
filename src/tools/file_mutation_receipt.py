"""Structured receipts and postcondition checks for text file mutations."""

from __future__ import annotations

import difflib
import hashlib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from src.tools.effects import STATUS_COMPLETED

if TYPE_CHECKING:
    from pathlib import Path

    from src.tools.effects import ToolEffect

FILE_CREATED = "file.create"
FILE_APPENDED = "file.append"
FILE_EDITED = "file.edit"
FILE_REPLACED = "file.replace"
FILE_MUTATION_ACTIONS = frozenset({FILE_CREATED, FILE_APPENDED, FILE_EDITED, FILE_REPLACED})
FILE_WRITTEN = "file_written"
MUTATION_RECEIPT_KEY = "file_mutation"
VERIFIED_POSTCONDITION = "verified"
SHA256_HEX_LENGTH = 64


@dataclass(frozen=True)
class ChangedLineRange:
    """One deterministic line-level change between two file versions."""

    kind: str
    before_start: int
    before_end: int
    after_start: int
    after_end: int

    def to_dict(self) -> dict[str, int | str]:
        return {
            "kind": self.kind,
            "before_start": self.before_start,
            "before_end": self.before_end,
            "after_start": self.after_start,
            "after_end": self.after_end,
        }


@dataclass(frozen=True)
class FileMutationReceipt:
    """Evidence produced only after a file mutation passes its postconditions."""

    operation: str
    canonical_path: str
    before_sha256: str
    after_sha256: str
    before_size: int
    after_size: int
    changed_ranges: tuple[ChangedLineRange, ...]
    snapshot_path: str = ""
    appended_sha256: str = ""
    postcondition: str = VERIFIED_POSTCONDITION

    def to_dict(self) -> dict[str, Any]:
        return {
            "operation": self.operation,
            "canonical_path": self.canonical_path,
            "before_sha256": self.before_sha256,
            "after_sha256": self.after_sha256,
            "before_size": self.before_size,
            "after_size": self.after_size,
            "changed_ranges": [item.to_dict() for item in self.changed_ranges],
            "snapshot_path": self.snapshot_path,
            "appended_sha256": self.appended_sha256,
            "postcondition": self.postcondition,
        }


def content_sha256(content: bytes) -> str:
    """Return a stable SHA-256 digest for file content."""
    return hashlib.sha256(content).hexdigest()


def changed_line_ranges(before: bytes, after: bytes) -> tuple[ChangedLineRange, ...]:
    """Return deterministic changed line ranges for a text mutation."""
    before_lines = before.decode("utf-8").splitlines()
    after_lines = after.decode("utf-8").splitlines()
    matcher = difflib.SequenceMatcher(a=before_lines, b=after_lines, autojunk=False)
    return tuple(
        ChangedLineRange(tag, left_start + 1, left_end, right_start + 1, right_end)
        for tag, left_start, left_end, right_start, right_end in matcher.get_opcodes()
        if tag != "equal"
    )


def mutation_receipt_from_effect(effect: ToolEffect) -> FileMutationReceipt | None:
    """Parse a mutation receipt from a structured tool effect."""
    raw_receipt = effect.details.get(MUTATION_RECEIPT_KEY)
    if not isinstance(raw_receipt, dict):
        return None
    try:
        ranges = tuple(_changed_range(item) for item in raw_receipt["changed_ranges"])
        return FileMutationReceipt(
            operation=str(raw_receipt["operation"]),
            canonical_path=str(raw_receipt["canonical_path"]),
            before_sha256=str(raw_receipt["before_sha256"]),
            after_sha256=str(raw_receipt["after_sha256"]),
            before_size=int(raw_receipt["before_size"]),
            after_size=int(raw_receipt["after_size"]),
            changed_ranges=ranges,
            snapshot_path=str(raw_receipt.get("snapshot_path") or ""),
            appended_sha256=str(raw_receipt.get("appended_sha256") or ""),
            postcondition=str(raw_receipt["postcondition"]),
        )
    except (KeyError, TypeError, ValueError):
        return None


def verified_file_mutation(effect: ToolEffect, project_root: Path | None) -> bool:
    """Verify a structured mutation receipt against the final filesystem state."""
    receipt = mutation_receipt_from_effect(effect)
    if not _effect_matches_receipt(effect, receipt):
        return False
    assert receipt is not None
    if project_root is None:
        return False
    target = _resolved_project_path(project_root, receipt.canonical_path)
    if target is None or not target.is_file():
        return False
    try:
        current_content = target.read_bytes()
    except OSError:
        return False
    if not _current_content_matches(receipt, current_content):
        return False
    try:
        return _source_content_matches(receipt, project_root, current_content)
    except UnicodeDecodeError:
        return False


def _changed_range(raw_range: Any) -> ChangedLineRange:
    if not isinstance(raw_range, dict):
        raise TypeError("changed range must be an object")
    return ChangedLineRange(
        kind=str(raw_range["kind"]),
        before_start=int(raw_range["before_start"]),
        before_end=int(raw_range["before_end"]),
        after_start=int(raw_range["after_start"]),
        after_end=int(raw_range["after_end"]),
    )


def _effect_matches_receipt(
    effect: ToolEffect,
    receipt: FileMutationReceipt | None,
) -> bool:
    if receipt is None or effect.status != STATUS_COMPLETED or effect.effect != FILE_WRITTEN:
        return False
    target = effect.resource.canonical if effect.resource else effect.target
    return (
        effect.action in FILE_MUTATION_ACTIONS
        and receipt.operation == effect.action
        and receipt.canonical_path == target
        and receipt.postcondition == VERIFIED_POSTCONDITION
        and receipt.before_size >= 0
        and receipt.after_size >= 0
        and len(receipt.after_sha256) == SHA256_HEX_LENGTH
    )


def _current_content_matches(receipt: FileMutationReceipt, current_content: bytes) -> bool:
    return (
        len(current_content) == receipt.after_size
        and content_sha256(current_content) == receipt.after_sha256
    )


def _source_content_matches(
    receipt: FileMutationReceipt,
    project_root: Path,
    current_content: bytes,
) -> bool:
    if receipt.operation == FILE_CREATED:
        return _created_receipt_matches(receipt, current_content)
    snapshot = _resolved_project_path(project_root, receipt.snapshot_path)
    if snapshot is None or not snapshot.is_file():
        return False
    try:
        before_content = snapshot.read_bytes()
    except OSError:
        return False
    if not _snapshot_matches(receipt, before_content):
        return False
    if changed_line_ranges(before_content, current_content) != receipt.changed_ranges:
        return False
    return receipt.operation != FILE_APPENDED or _append_matches(
        receipt,
        before_content,
        current_content,
    )


def _created_receipt_matches(receipt: FileMutationReceipt, current_content: bytes) -> bool:
    return (
        receipt.before_sha256 == ""
        and receipt.before_size == 0
        and receipt.snapshot_path == ""
        and changed_line_ranges(b"", current_content) == receipt.changed_ranges
    )


def _snapshot_matches(receipt: FileMutationReceipt, before_content: bytes) -> bool:
    return (
        len(receipt.before_sha256) == SHA256_HEX_LENGTH
        and len(before_content) == receipt.before_size
        and content_sha256(before_content) == receipt.before_sha256
    )


def _append_matches(
    receipt: FileMutationReceipt,
    before_content: bytes,
    current_content: bytes,
) -> bool:
    if not current_content.startswith(before_content):
        return False
    appended_content = current_content[len(before_content) :]
    return (
        len(receipt.appended_sha256) == SHA256_HEX_LENGTH
        and content_sha256(appended_content) == receipt.appended_sha256
    )


def _resolved_project_path(project_root: Path, relative_path: str) -> Path | None:
    if not relative_path:
        return None
    try:
        target = (project_root.resolve() / relative_path).resolve()
    except (OSError, RuntimeError):
        return None
    return target if target.is_relative_to(project_root.resolve()) else None
