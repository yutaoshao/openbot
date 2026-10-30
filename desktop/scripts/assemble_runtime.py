"""Assemble a pinned arm64 probe runtime without reading application user data."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path

from runtime_artifacts import copy_python_source, download_artifact, extract_archive, sha256

DESKTOP = Path(__file__).resolve().parents[1]
REPOSITORY = DESKTOP.parent


def build_environment(cache: Path) -> dict[str, str]:
    environment = {"PATH": os.defpath, "LANG": "en_US.UTF-8"}
    environment["UV_CACHE_DIR"] = str(cache / "uv")
    environment["UV_PYTHON_DOWNLOADS"] = "never"
    environment["UV_NO_PROGRESS"] = "1"
    return environment


def install_dependencies(runtime: Path, cache: Path, uv: Path) -> None:
    requirements = runtime / "requirements.lock.txt"
    environment = build_environment(cache)
    subprocess.run(
        [
            str(uv),
            "--no-config",
            "export",
            "--frozen",
            "--offline",
            "--no-dev",
            "--no-header",
            "--no-annotate",
            "--no-emit-project",
            "--output-file",
            str(requirements),
        ],
        cwd=REPOSITORY,
        env=environment,
        check=True,
        stdout=subprocess.DEVNULL,
        timeout=60,
    )
    subprocess.run(
        [
            str(uv),
            "--no-config",
            "pip",
            "install",
            "--python",
            str(runtime / "bin/python3"),
            "--target",
            str(runtime / "lib/python3.12/site-packages"),
            "--require-hashes",
            "--no-deps",
            "--only-binary",
            ":all:",
            "--index-url",
            "https://pypi.org/simple",
            "--requirements",
            str(requirements),
        ],
        cwd=cache,
        env=environment,
        check=True,
        timeout=240,
    )


def add_ripgrep(runtime: Path, archive: Path, temporary: Path) -> None:
    destination = temporary / "ripgrep"
    extract_archive(archive, destination)
    folders = list(destination.iterdir())
    if len(folders) != 1 or not (folders[0] / "rg").is_file():
        raise ValueError("Unexpected ripgrep archive layout")
    shutil.copy2(folders[0] / "rg", runtime / "bin/rg")
    licenses = runtime / "licenses/ripgrep"
    licenses.mkdir(parents=True)
    for path in folders[0].iterdir():
        if path.is_file() and path.name.startswith(("LICENSE", "COPYING", "UNLICENSE", "README")):
            shutil.copy2(path, licenses / path.name)


def add_tokenizers(runtime: Path, specs: dict, cache: Path) -> None:
    destination = runtime / "tokenizer-cache"
    destination.mkdir()
    for spec in specs.values():
        artifact = download_artifact(spec, cache)
        cache_key = hashlib.sha1(spec["url"].encode(), usedforsecurity=False).hexdigest()
        shutil.copy2(artifact, destination / cache_key)


def validate_output(output: Path, replace: bool) -> None:
    if not output.exists():
        return
    entries = {p.name for p in output.iterdir()}
    if entries <= {"README.md"}:
        return
    if not replace or not (output / "build-manifest.json").is_file():
        raise ValueError(
            "Existing runtime is not empty; use --replace only for a generated runtime"
        )


def publish(runtime: Path, output: Path, cache: Path) -> None:
    readme = output / "README.md"
    if readme.is_file():
        shutil.copy2(readme, runtime / "README.md")
    if output.exists():
        backup = cache / "backups" / uuid.uuid4().hex
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(output), backup)
        print(f"Previous generated runtime preserved at {backup}", flush=True)
    shutil.move(str(runtime), output)


def assemble(cache: Path, replace: bool) -> dict:
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        raise ValueError("This runtime assembly is for Apple Silicon macOS only")
    uv_path = shutil.which("uv")
    if uv_path is None:
        raise ValueError("Build-time uv executable is required")
    uv = Path(uv_path).resolve()
    output = DESKTOP / "runtime"
    validate_output(output, replace)
    cache.mkdir(parents=True, exist_ok=True)
    sources = json.loads((DESKTOP / "probe/runtime-sources.json").read_text())
    python = download_artifact(sources["python"], cache)
    ripgrep = download_artifact(sources["ripgrep"], cache)
    with tempfile.TemporaryDirectory(prefix="assemble-", dir=cache) as temporary:
        stage = Path(temporary)
        extract_archive(python, stage)
        runtime = stage / "python"
        if not (runtime / "bin/python3").exists():
            raise ValueError("Unexpected Python archive layout")
        install_dependencies(runtime, cache, uv)
        add_ripgrep(runtime, ripgrep, stage)
        add_tokenizers(runtime, sources["tokenizers"], cache)
        source_hashes = copy_python_source(REPOSITORY / "src", runtime / "app/src")
        manifest = {
            "status": "assembled_not_signed_or_clean_machine_verified",
            "sources": sources,
            "uv_lock_sha256": sha256(REPOSITORY / "uv.lock"),
            "requirements_sha256": sha256(runtime / "requirements.lock.txt"),
            "source_sha256": source_hashes,
        }
        (runtime / "build-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        publish(runtime, output, cache)
    return {"runtime": str(output), "manifest": str(output / "build-manifest.json")}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cache-dir", type=Path, default=Path("/private/tmp/openbot-runtime-downloads")
    )
    parser.add_argument("--replace", action="store_true")
    args = parser.parse_args()
    print(json.dumps(assemble(args.cache_dir.resolve(), args.replace), indent=2))


if __name__ == "__main__":
    main()
