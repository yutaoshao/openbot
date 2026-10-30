"""Reject invalid build artifacts and stage only application Python source."""

from __future__ import annotations

import importlib.util
import io
import tarfile
from pathlib import Path

import pytest

ARTIFACTS = Path(__file__).parents[2] / "desktop/scripts/runtime_artifacts.py"
spec = importlib.util.spec_from_file_location("runtime_artifacts", ARTIFACTS)
assert spec and spec.loader
artifacts = importlib.util.module_from_spec(spec)
spec.loader.exec_module(artifacts)


def test_checksum_mismatch_rejected(tmp_path):
    artifact = tmp_path / "artifact"
    artifact.write_bytes(b"changed download")
    with pytest.raises(ValueError, match="SHA256 mismatch"):
        artifacts.verify_hash(artifact, "0" * 64)


def test_archive_cannot_write_outside_destination(tmp_path):
    archive = tmp_path / "unsafe.tar.gz"
    with tarfile.open(archive, "w:gz") as stream:
        member = tarfile.TarInfo("../outside")
        member.size = 1
        stream.addfile(member, io.BytesIO(b"x"))
    with pytest.raises(tarfile.FilterError):
        artifacts.extract_archive(archive, tmp_path / "extract")
    assert not (tmp_path / "outside").exists()


def test_source_staging_excludes_cache_private_data_and_external_symlinks(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "module.py").write_text("x = 1\n")
    (source / ".env").write_text("SYNTHETIC_TOKEN=not-a-real-secret\n")
    (source / "__pycache__").mkdir()
    (source / "__pycache__/cached.py").write_text("cached = True\n")
    (tmp_path / "external.py").write_text("external = True\n")
    (source / "link.py").symlink_to(tmp_path / "external.py")
    destination = tmp_path / "destination"
    assert set(artifacts.copy_python_source(source, destination)) == {"module.py"}
    assert [p.name for p in destination.iterdir()] == ["module.py"]
