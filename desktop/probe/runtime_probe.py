"""Offline P1 runtime checks; never load user configuration or start channels."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import hashlib
import importlib.metadata
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def check_result(name: str, action) -> dict:
    try:
        return {"name": name, "status": "passed", "details": action()}
    except Exception as error:
        return {"name": name, "status": "failed", "error": str(error)}


def check_python(expected_runtime: Path | None = None) -> dict:
    if sys.version_info < (3, 12):  # noqa: UP036 - Probe may run under a wrong bundled interpreter.
        raise RuntimeError("Python 3.12 or newer is required")
    if expected_runtime is not None:
        root = expected_runtime.resolve()
        for path in (Path(sys.executable).resolve(), Path(sys.base_prefix).resolve()):
            if not path.is_relative_to(root):
                raise RuntimeError("Python executable or base prefix escapes expected runtime")
    return {
        "version": platform.python_version(),
        "architecture": platform.machine(),
        "executable": str(Path(sys.executable).resolve()),
    }


def check_imports() -> dict:
    modules = {
        "fastapi": "fastapi",
        "uvicorn": "uvicorn",
        "pydantic": "pydantic",
        "aiosqlite": "aiosqlite",
        "sqlite-vec": "sqlite_vec",
        "tiktoken": "tiktoken",
        "anthropic": "anthropic",
        "openai": "openai",
        "dashscope": "dashscope",
        "lark-oapi": "lark_oapi",
        "python-telegram-bot": "telegram",
        "trafilatura": "trafilatura",
        "tavily-python": "tavily",
    }
    versions = {}
    for distribution, module in modules.items():
        __import__(module)
        versions[distribution] = importlib.metadata.version(distribution)
    return versions


async def check_database_async(directory: Path) -> dict:
    from src.core.config import StorageConfig
    from src.infrastructure.database import SCHEMA_VERSION, Database

    database = Database(StorageConfig(db_path=str(directory / "probe.db")))
    try:
        await database.initialize()
        cursor = await database.connection.execute("SELECT vec_version()")
        row = await cursor.fetchone()
        return {"schema_version": SCHEMA_VERSION, "sqlite_vec_version": row[0]}
    finally:
        await database.close()


def check_tokenizer() -> dict:
    import tiktoken

    encoding = tiktoken.Encoding(
        name="openbot_offline_probe",
        pat_str=r"(?s).",
        mergeable_ranks={bytes([value]): value for value in range(256)},
        special_tokens={},
    )
    sample = "OpenBot 离线探测"
    tokens = encoding.encode(sample)
    if encoding.decode(tokens) != sample:
        raise RuntimeError("Native tokenizer roundtrip failed")
    return {"native_roundtrip": True, "production_encoding_resources": "not_verified"}


def check_search(rg: Path, directory: Path) -> dict:
    sample = directory / "fixture.txt"
    sample.write_text("openbot-probe-fixture\n", encoding="utf-8")
    result = subprocess.run(
        [str(rg), "--no-config", "--fixed-strings", "openbot-probe-fixture", str(sample)],
        cwd=directory,
        env={"PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        timeout=5,
        check=True,
    )
    if result.stdout.strip() != "openbot-probe-fixture":
        raise RuntimeError("Unexpected ripgrep output")
    return {"explicit_binary": str(rg), "search": True}


def check_production_tokenizers(cache: Path) -> dict:
    import tiktoken

    specs = json.loads(Path(__file__).with_name("runtime-sources.json").read_text())["tokenizers"]
    for name, spec in specs.items():
        key = hashlib.sha1(spec["url"].encode(), usedforsecurity=False).hexdigest()
        artifact = cache / key
        if (
            not artifact.is_file()
            or hashlib.sha256(artifact.read_bytes()).hexdigest() != spec["sha256"]
        ):
            raise RuntimeError(f"Missing or invalid production tokenizer cache: {name}")
    os.environ["TIKTOKEN_CACHE_DIR"] = str(cache.resolve())
    for name in specs:
        encoding = tiktoken.get_encoding(name)
        if encoding.decode(encoding.encode("OpenBot 真实编码验证")) != "OpenBot 真实编码验证":
            raise RuntimeError(f"Production tokenizer roundtrip failed: {name}")
    return {"encodings": list(specs), "sha256_verified": True, "offline_roundtrip": True}


def check_child(directory: Path) -> dict:
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-B",
            "-c",
            "import json,sys; print(json.dumps({"
            "'major':sys.version_info.major,'minor':sys.version_info.minor,'result':6*7}))",
        ],
        cwd=directory,
        env={"PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        timeout=5,
        check=True,
    )
    payload = json.loads(result.stdout)
    if (payload["major"], payload["minor"]) < (3, 12) or payload["result"] != 42:
        raise RuntimeError("Explicit interpreter child failed")
    return payload


async def check_existing_executor_async() -> dict:
    from src.tools.builtin.code_executor import CodeExecutorTool

    result = await CodeExecutorTool().execute(
        {
            "code": "import json,sys,site; print(json.dumps({"
            "'version':list(sys.version_info[:2]),'executable':sys.executable,"
            "'user_site_enabled':bool(site.ENABLE_USER_SITE),"
            "'user_site_on_path':site.getusersitepackages() in sys.path}))",
            "timeout": 5,
        }
    )
    if result.is_error:
        raise RuntimeError(result.content)
    # The existing tool appends captured stderr after its stdout text.
    payload = json.loads(result.content.splitlines()[0])
    if payload["version"] != list(sys.version_info[:2]):
        raise RuntimeError(
            "Existing CodeExecutor resolves a different interpreter: "
            f"{payload['version']}; expected {list(sys.version_info[:2])}. "
            "Core integration must explicitly select the bundled interpreter."
        )
    if Path(payload["executable"]).resolve() != Path(sys.executable).resolve():
        raise RuntimeError("Existing CodeExecutor did not use the current runtime executable")
    if payload["user_site_enabled"] or payload["user_site_on_path"]:
        raise RuntimeError("Existing CodeExecutor permits host user-site packages")
    return payload


def run_probe(
    source_root: Path,
    rg: Path | None,
    *,
    tokenizer_cache: Path | None = None,
    expected_runtime: Path | None = None,
) -> dict:
    source_root = source_root.resolve()
    if not (source_root / "src/infrastructure/database.py").is_file():
        raise ValueError("Source root must contain OpenBot source, not user configuration")
    sys.path.insert(0, str(source_root))
    production = []
    if tokenizer_cache is not None:
        production.append(
            check_result(
                "production_tokenizers",
                lambda: check_production_tokenizers(tokenizer_cache),
            )
        )
        if production[0]["status"] != "passed":
            return {"protocol_version": 1, "status": "failed", "checks": production}
    with tempfile.TemporaryDirectory(prefix="openbot-runtime-probe-") as temporary:
        directory = Path(temporary)
        with contextlib.redirect_stdout(sys.stderr):
            checks = production + [
                check_result("python", lambda: check_python(expected_runtime)),
                check_result("imports", check_imports),
            ]
            checks.append(
                check_result("database", lambda: asyncio.run(check_database_async(directory)))
            )
            checks.append(check_result("tokenizer_native", check_tokenizer))
            checks.append(check_result("explicit_python_child", lambda: check_child(directory)))
            checks.append(
                check_result(
                    "existing_code_executor", lambda: asyncio.run(check_existing_executor_async())
                )
            )
            if rg is None:
                checks.append(
                    {
                        "name": "ripgrep",
                        "status": "failed",
                        "error": "Explicit rg binary unavailable",
                    }
                )
            else:
                checks.append(
                    check_result("ripgrep", lambda: check_search(rg.resolve(), directory))
                )
    return {
        "protocol_version": 1,
        "mode": "offline_runtime_probe",
        "status": "passed" if all(item["status"] == "passed" for item in checks) else "failed",
        "checks": checks,
        "not_verified": [
            "clean machine installation",
            "signed native loading",
            "real model and channel workflows",
            "complete application startup",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--rg", type=Path, default=None)
    parser.add_argument("--tokenizer-cache", type=Path, default=None)
    parser.add_argument("--expected-runtime", type=Path, default=None)
    args = parser.parse_args()
    rg = args.rg or (Path(found) if (found := shutil.which("rg")) else None)
    report = run_probe(
        args.source_root,
        rg,
        tokenizer_cache=args.tokenizer_cache,
        expected_runtime=args.expected_runtime,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
