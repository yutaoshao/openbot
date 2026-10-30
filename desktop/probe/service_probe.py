"""External CLI smoke of packaged Application with loopback fake model only."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from service_fake import REPLY, FakeOpenAI  # noqa: E402
from service_guard import (  # noqa: E402
    audit_synthetic_io,
    evaluate_worker_report,
    verify_dotenv_disabled,
)


def synthetic_config(model_port: int) -> dict:
    return {
        "model": {
            "primary": {
                "provider": "openai_compatible",
                "model": "openbot-service-probe",
                "base_url": f"http://127.0.0.1:{model_port}/v1",
                "api_key_env": "OPENBOT_PROBE_KEY",
                "max_tokens": 128,
                "connect_timeout": 3,
                "read_timeout": 5,
            },
            "max_retries": 1,
            "fallback": None,
            "routing": {"enabled": False},
        },
        "telegram": {"enabled": False},
        "feishu": {"enabled": False},
        "wechat": {"enabled": False},
        "embedding": {"enabled": False},
        "reranker": {"enabled": False},
        "log": {"file": None, "otlp_endpoint": None},
        "scheduler": {"timezone": "UTC"},
        "storage": {"db_path": "data/probe.db"},
        "api": {
            "enabled": True,
            "host": "127.0.0.1",
            "port": 0,
            "local_only": True,
            "serve_frontend": False,
        },
        "agent": {
            "max_iterations": 2,
            "task_timeout": 15,
            "tool_timeout": 3,
            "system_prompt": "Answer the consultation briefly. Do not use tools.",
        },
    }


async def exercise_service(model: FakeOpenAI) -> dict:
    import httpx

    from src.application import Application

    app = Application()
    if (
        any(
            config.enabled
            for config in (
                app.config.telegram,
                app.config.feishu,
                app.config.wechat,
                app.config.embedding,
                app.config.reranker,
            )
        )
        or app.config.log.otlp_endpoint is not None
    ):
        raise RuntimeError("External integrations must be disabled in synthetic config")
    try:
        await app.start()
        port = app.api_server.servers[0].sockets[0].getsockname()[1]
        async with httpx.AsyncClient(
            base_url=f"http://127.0.0.1:{port}", trust_env=False, timeout=20
        ) as client:
            health = await client.get("/health")
            health.raise_for_status()
            if health.json()["status"] != "ok":
                raise RuntimeError("Application health body is not ready")
            response = await client.post(
                "/api/chat",
                json={
                    "message": "Explain inverse kinematics briefly without using tools.",
                    "platform": "web",
                },
            )
            response.raise_for_status()
            payload = response.json()
            if payload["reply"] != REPLY or not payload["conversation_id"]:
                raise RuntimeError("REST chat did not return the synthetic model reply")
        cursor = await app.database.connection.execute(
            "SELECT COUNT(*) FROM messages WHERE conversation_id = ?",
            (payload["conversation_id"],),
        )
        count = (await cursor.fetchone())[0]
        if count < 2 or model.requests < 1:
            raise RuntimeError("Chat was not persisted or did not reach the fake model")
        result = {
            "health_http_status": health.status_code,
            "rest_http_status": response.status_code,
            "reply_matches": True,
            "persisted_messages": count,
            "fake_model_requests": model.requests,
        }
    finally:
        await app.stop()
    result["shutdown_complete"] = app.api_task is None and app.housekeeping_task is None
    result["fake_model_requests"] = model.requests
    result["external_integrations_disabled"] = True
    try:
        _ = app.database.connection
    except RuntimeError:
        result["database_closed"] = True
    else:
        raise RuntimeError("Database still open after shutdown")
    return result


def worker(source_root: Path, workspace: Path) -> dict:
    workspace = workspace.resolve()
    if Path.cwd().resolve() != workspace:
        raise RuntimeError("Worker cwd must be the synthetic workspace")
    version = verify_dotenv_disabled()
    sys.addaudithook(lambda event, args: audit_synthetic_io(workspace, event, args))
    synthetic_home = workspace / "home"
    synthetic_home.mkdir()
    model = FakeOpenAI()
    try:
        (workspace / "config.yaml").write_text(json.dumps(synthetic_config(model.server_port)))
        sys.path.insert(0, str(source_root.resolve()))
        model.start()
        with patch.object(Path, "home", return_value=synthetic_home):
            result = asyncio.run(exercise_service(model))
    finally:
        model.stop()
    return {
        "status": "passed",
        "mode": "packaged_service_fake_model_smoke",
        "dotenv_disabled_verified": True,
        "python_dotenv_version": version,
        "synthetic_home": True,
        "loopback_only": True,
        **result,
        "not_verified": [
            "real model",
            "real channels",
            "native service launcher",
            "signed distribution",
            "clean machine",
        ],
    }


def run_controller(app: Path) -> dict:
    runtime = app.resolve() / "Contents/Resources/runtime"
    if not (runtime / "bin/python3").is_file():
        raise ValueError("Expected an assembled preview .app")
    with tempfile.TemporaryDirectory(prefix="openbot-service-probe-") as temporary:
        environment = {
            "PATH": "/usr/bin:/bin",
            "PYTHON_DOTENV_DISABLED": "1",
            "TIKTOKEN_CACHE_DIR": str(runtime / "tokenizer-cache"),
            "OPENBOT_PROBE_KEY": "synthetic-service-probe-key",
            "OTEL_SDK_DISABLED": "true",
        }
        result = subprocess.run(
            [
                str(runtime / "bin/python3"),
                "-I",
                "-B",
                str(Path(__file__).resolve()),
                "--worker",
                "--source-root",
                str(runtime / "app"),
                "--workspace",
                temporary,
            ],
            cwd=temporary,
            env=environment,
            capture_output=True,
            text=True,
            timeout=60,
        )
    if result.stderr:
        print(result.stderr, file=sys.stderr)
    if not result.stdout:
        raise RuntimeError(f"Service worker exited {result.returncode} without a report")
    report = json.loads(result.stdout)
    return evaluate_worker_report(report, result.stderr, result.returncode)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", type=Path)
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--workspace", type=Path)
    args = parser.parse_args()
    try:
        with contextlib.redirect_stdout(sys.stderr):
            if args.worker:
                if args.source_root is None or args.workspace is None:
                    raise ValueError("Worker requires source and workspace")
                report = worker(args.source_root, args.workspace)
            elif args.app is not None:
                report = run_controller(args.app)
            else:
                raise ValueError("--app is required")
    except Exception as error:
        traceback.print_exc(file=sys.stderr)
        report = {"status": "failed", "error": f"{type(error).__name__}: {error}"}
    print(json.dumps(report, indent=2))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
