"""Release preparation validates explicit public inputs without reading credentials."""

from __future__ import annotations

import base64
import json

import pytest

from desktop.scripts.release_manifest import release_manifest
from desktop.scripts.release_prepare import prepare_release


def public_key():
    line = base64.b64encode(b"Ed" + b"x" * 40).decode()
    return base64.b64encode(("untrusted comment: synthetic public key\n" + line).encode()).decode()


@pytest.fixture
def project(tmp_path):
    for directory in ("desktop/src-tauri", "frontend", "desktop"):
        (tmp_path / directory).mkdir(parents=True, exist_ok=True)
    for name in (
        "desktop/src-tauri/tauri.conf.json",
        "frontend/package.json",
        "desktop/package.json",
    ):
        (tmp_path / name).write_text(json.dumps({"version": "0.1.0"}))
    (tmp_path / "desktop/src-tauri/Cargo.toml").write_text('[package]\nversion = "0.1.0"\n')
    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "0.1.0"\n')
    return tmp_path


def test_release_plan_keeps_versions_and_requires_signature_and_https(project):
    original = (project / "desktop/src-tauri/tauri.conf.json").read_bytes()
    plan = prepare_release(
        project,
        "https://updates.example.test/latest.json",
        public_key(),
        "Developer ID Application: Synthetic",
        "15.0",
    )
    assert plan["version"] == "0.1.0"
    assert plan["overlay"]["plugins"]["updater"]["requireSignedVersion"]
    assert plan["overlay"]["bundle"]["createUpdaterArtifacts"]
    assert "PRIVATE" not in str(plan["compile_environment"])
    assert (project / "desktop/src-tauri/tauri.conf.json").read_bytes() == original


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://updates.example.test",
        "https://key:secret@example.test",
        "file:///tmp/update",
        "https://example.test/#x",
    ],
)
def test_release_plan_rejects_untrusted_endpoints(project, endpoint):
    with pytest.raises(ValueError):
        prepare_release(
            project, endpoint, public_key(), "Developer ID Application: Synthetic", "15.0"
        )


def test_release_plan_rejects_private_key_or_version_mismatch(project):
    with pytest.raises(ValueError, match="公开"):
        prepare_release(
            project,
            "https://example.test/update",
            "private-key-do-not-accept",
            "Developer ID Application: Synthetic",
            "15.0",
        )
    (project / "frontend/package.json").write_text('{"version":"0.2.0"}')
    with pytest.raises(ValueError, match="版本"):
        prepare_release(
            project,
            "https://example.test/update",
            public_key(),
            "Developer ID Application: Synthetic",
            "15.0",
        )


def test_manifest_requires_exact_version_binding_and_does_not_publish(tmp_path):
    artifact = tmp_path / "OpenBot.app.tar.gz"
    artifact.write_bytes(b"synthetic-artifact-not-a-real-release")
    signature = tmp_path / "OpenBot.app.tar.gz.sig"
    signature.write_text(
        base64.b64encode(
            b"untrusted comment: synthetic\nx\ntrusted comment: timestamp:1\t"
            b"file:OpenBot.app.tar.gz\tversion:0.1.0\nx"
        ).decode()
    )
    manifest = release_manifest(
        "0.1.0", artifact, signature, "https://example.test/OpenBot.app.tar.gz", "synthetic"
    )
    assert manifest["platforms"]["darwin-aarch64"]["url"].startswith("https:")
    with pytest.raises(ValueError, match="版本"):
        release_manifest(
            "0.2.0", artifact, signature, "https://example.test/OpenBot.app.tar.gz", "synthetic"
        )
