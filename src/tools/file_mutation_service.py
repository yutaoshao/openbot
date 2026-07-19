"""Serialized, snapshotted, atomic text file mutations."""

from __future__ import annotations

import os
import shutil
import tempfile
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from stat import S_IMODE
from typing import TYPE_CHECKING

from src.tools.builtin.path_utils import project_root, relative_to_root
from src.tools.file_mutation_receipt import (
    FILE_APPENDED,
    FILE_CREATED,
    FILE_EDITED,
    FILE_REPLACED,
    FileMutationReceipt,
    changed_line_ranges,
    content_sha256,
)

SNAPSHOT_DIRECTORY = Path("data/file_snapshots")
SNAPSHOT_TIMESTAMP_FORMAT = "%Y%m%dT%H%M%S%f"
UTF8 = "utf-8"

if TYPE_CHECKING:
    from collections.abc import Iterator


class FileMutationError(RuntimeError):
    """Raised when a requested mutation would violate a file invariant."""


class FileMutationService:
    """Own text mutation locking, snapshots, atomic commits, and receipts."""

    def __init__(self, root: Path, snapshot_directory: Path = SNAPSHOT_DIRECTORY) -> None:
        self._root = project_root(root)
        self._snapshot_root = (self._root / snapshot_directory).resolve()
        if not self._snapshot_root.is_relative_to(self._root):
            raise ValueError("snapshot directory must stay inside project root")
        self._locks: dict[Path, threading.Lock] = {}
        self._locks_guard = threading.Lock()

    @property
    def project_root(self) -> Path:
        return self._root

    def create(self, target: Path, content: str) -> FileMutationReceipt:
        """Create a new text file and reject existing targets."""
        encoded_content = content.encode(UTF8)
        with self._serialized_target(target) as canonical_target:
            if canonical_target.exists():
                raise FileMutationError(
                    "Target already exists; use append_file, edit_file, or replace_file",
                )
            canonical_target.parent.mkdir(parents=True, exist_ok=True)
            self._atomic_create(canonical_target, encoded_content)
            current_content = self._verified_content(canonical_target, encoded_content)
            return FileMutationReceipt(
                operation=FILE_CREATED,
                canonical_path=relative_to_root(self._root, canonical_target),
                before_sha256="",
                after_sha256=content_sha256(current_content),
                before_size=0,
                after_size=len(current_content),
                changed_ranges=changed_line_ranges(b"", current_content),
            )

    def append(self, target: Path, content: str) -> FileMutationReceipt:
        """Append text while preserving the complete existing file prefix."""
        appended_content = content.encode(UTF8)
        if not appended_content:
            raise FileMutationError("Append content must not be empty")
        with self._serialized_target(target) as canonical_target:
            before_content = self._existing_text(canonical_target)
            snapshot = self._snapshot(canonical_target, before_content)
            expected_content = before_content + appended_content
            self._atomic_replace(canonical_target, expected_content)
            current_content = self._verified_content(canonical_target, expected_content)
            if not current_content.startswith(before_content):
                raise FileMutationError("Append postcondition failed: original prefix changed")
            return FileMutationReceipt(
                operation=FILE_APPENDED,
                canonical_path=relative_to_root(self._root, canonical_target),
                before_sha256=content_sha256(before_content),
                after_sha256=content_sha256(current_content),
                before_size=len(before_content),
                after_size=len(current_content),
                changed_ranges=changed_line_ranges(before_content, current_content),
                snapshot_path=relative_to_root(self._root, snapshot),
                appended_sha256=content_sha256(appended_content),
            )

    def edit(
        self,
        target: Path,
        expected_sha256: str,
        content: str,
    ) -> FileMutationReceipt:
        """Commit a targeted edit only when the source version still matches."""
        encoded_content = content.encode(UTF8)
        with self._serialized_target(target) as canonical_target:
            before_content = self._matching_text(canonical_target, expected_sha256)
            self._require_content_change(before_content, encoded_content)
            snapshot = self._snapshot(canonical_target, before_content)
            self._atomic_replace(canonical_target, encoded_content)
            current_content = self._verified_content(canonical_target, encoded_content)
            return FileMutationReceipt(
                operation=FILE_EDITED,
                canonical_path=relative_to_root(self._root, canonical_target),
                before_sha256=content_sha256(before_content),
                after_sha256=content_sha256(current_content),
                before_size=len(before_content),
                after_size=len(current_content),
                changed_ranges=changed_line_ranges(before_content, current_content),
                snapshot_path=relative_to_root(self._root, snapshot),
            )

    def replace(
        self,
        target: Path,
        expected_sha256: str,
        content: str,
    ) -> FileMutationReceipt:
        """Replace a complete file only when the caller supplies its current hash."""
        encoded_content = content.encode(UTF8)
        with self._serialized_target(target) as canonical_target:
            before_content = self._matching_text(canonical_target, expected_sha256)
            self._require_content_change(before_content, encoded_content)
            snapshot = self._snapshot(canonical_target, before_content)
            self._atomic_replace(canonical_target, encoded_content)
            current_content = self._verified_content(canonical_target, encoded_content)
            return FileMutationReceipt(
                operation=FILE_REPLACED,
                canonical_path=relative_to_root(self._root, canonical_target),
                before_sha256=content_sha256(before_content),
                after_sha256=content_sha256(current_content),
                before_size=len(before_content),
                after_size=len(current_content),
                changed_ranges=changed_line_ranges(before_content, current_content),
                snapshot_path=relative_to_root(self._root, snapshot),
            )

    @contextmanager
    def _serialized_target(self, target: Path) -> Iterator[Path]:
        canonical_target = target.resolve()
        if not canonical_target.is_relative_to(self._root):
            raise FileMutationError("Target is outside project root")
        with self._locks_guard:
            target_lock = self._locks.setdefault(canonical_target, threading.Lock())
        with target_lock:
            yield canonical_target

    def _existing_text(self, target: Path) -> bytes:
        if target.is_dir():
            raise FileMutationError("Target is a directory")
        if not target.is_file():
            raise FileMutationError("Target file does not exist")
        try:
            content = target.read_bytes()
            content.decode(UTF8)
            return content
        except UnicodeDecodeError as exc:
            raise FileMutationError("Target is not a UTF-8 text file") from exc
        except OSError as exc:
            raise FileMutationError(f"Read failed: {exc}") from exc

    def _matching_text(self, target: Path, expected_sha256: str) -> bytes:
        current_content = self._existing_text(target)
        if content_sha256(current_content) != expected_sha256:
            raise FileMutationError("File changed since it was read; mutation was not applied")
        return current_content

    def _require_content_change(self, before_content: bytes, after_content: bytes) -> None:
        if before_content == after_content:
            raise FileMutationError("Mutation would not change file content")

    def _snapshot(self, target: Path, expected_content: bytes) -> Path:
        relative_target = target.resolve().relative_to(self._root)
        snapshot_time = datetime.now()
        dated_root = self._snapshot_root / snapshot_time.strftime("%Y/%m/%d")
        snapshot_name = (
            f"{relative_target.name}.{snapshot_time.strftime(SNAPSHOT_TIMESTAMP_FORMAT)}."
            f"{uuid.uuid4().hex}.bak"
        )
        snapshot = dated_root / relative_target.parent / snapshot_name
        try:
            snapshot.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, snapshot)
            snapshot_content = snapshot.read_bytes()
        except OSError as exc:
            raise FileMutationError(f"Snapshot failed: {exc}") from exc
        if snapshot_content != expected_content:
            raise FileMutationError("Snapshot verification failed")
        return snapshot

    def _atomic_create(self, target: Path, content: bytes) -> None:
        temporary = self._write_temporary(target, content)
        try:
            os.link(temporary, target)
        except FileExistsError as exc:
            raise FileMutationError("Target already exists; file was not created") from exc
        except OSError as exc:
            raise FileMutationError(f"Create failed: {exc}") from exc
        finally:
            temporary.unlink(missing_ok=True)

    def _atomic_replace(self, target: Path, content: bytes) -> None:
        temporary = self._write_temporary(target, content)
        try:
            os.chmod(temporary, S_IMODE(target.stat().st_mode))
            os.replace(temporary, target)
        except OSError as exc:
            temporary.unlink(missing_ok=True)
            raise FileMutationError(f"Atomic replace failed: {exc}") from exc

    def _write_temporary(self, target: Path, content: bytes) -> Path:
        descriptor, raw_path = tempfile.mkstemp(
            prefix=f".{target.name}.",
            suffix=".tmp",
            dir=target.parent,
        )
        temporary = Path(raw_path)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
        except OSError as exc:
            temporary.unlink(missing_ok=True)
            raise FileMutationError(f"Temporary write failed: {exc}") from exc
        return temporary

    def _verified_content(self, target: Path, expected_content: bytes) -> bytes:
        try:
            current_content = target.read_bytes()
        except OSError as exc:
            raise FileMutationError(f"Post-write read failed: {exc}") from exc
        if current_content != expected_content:
            raise FileMutationError("Post-write content verification failed")
        return current_content
