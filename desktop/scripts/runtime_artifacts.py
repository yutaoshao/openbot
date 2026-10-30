"""Verified build artifacts and source staging for the desktop probe."""

from __future__ import annotations

import hashlib
import shutil
import tarfile
import urllib.request
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def verify_hash(path: Path, expected: str) -> None:
    if sha256(path) != expected:
        raise ValueError(f"SHA256 mismatch: {path.name}")


def download_artifact(spec: dict, cache: Path) -> Path:
    target = cache / spec["sha256"]
    if not target.exists():
        partial = target.with_suffix(".partial")
        request = urllib.request.Request(spec["url"], headers={"User-Agent": "OpenBot-P1"})
        with urllib.request.urlopen(request, timeout=120) as response, partial.open("wb") as stream:
            shutil.copyfileobj(response, stream)
        verify_hash(partial, spec["sha256"])
        partial.replace(target)
    verify_hash(target, spec["sha256"])
    return target


def extract_archive(archive: Path, destination: Path) -> None:
    with tarfile.open(archive, "r:gz") as stream:
        stream.extractall(destination, filter="data")


def copy_python_source(source: Path, destination: Path) -> dict[str, str]:
    source = source.resolve()
    hashes = {}
    for path in sorted(source.rglob("*.py")):
        if "__pycache__" in path.parts or not path.resolve().is_relative_to(source):
            continue
        relative = path.relative_to(source)
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        hashes[str(relative)] = sha256(target)
    return hashes
