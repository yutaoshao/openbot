"""Run packaged offline import, service settings and update-admission workflows."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import signal
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import yaml

PROBE_DIRECTORY = Path(__file__).resolve().parent
sys.path.insert(0, str(PROBE_DIRECTORY))
sys.path.insert(0, str(PROBE_DIRECTORY.parents[1]))
from desktop_service_probe import WRAPPER, chat, start, stop  # noqa: E402
from service_fake import FakeHandler, FakeOpenAI  # noqa: E402
from service_guard import evaluate_worker_report  # noqa: E402

from src.core.config import AppConfig  # noqa: E402
from src.core.user_scope import SINGLE_USER_ID  # noqa: E402
from src.infrastructure.database_schema import SCHEMA_SQL  # noqa: E402

CONVERSATION_ID = "synthetic-import-conversation"
SYNTHETIC_SECRET = "synthetic-search-key-never-return"


def synthetic_deployment(root: Path, model_port: int) -> Path:
    source = root / "old-deployment"
    data = source / "data"
    data.mkdir(parents=True)
    config = AppConfig(
        telegram={"enabled": False},
        model={
            "primary": {
                "provider": "openai_compatible",
                "model": "openbot-service-probe",
                "base_url": f"http://127.0.0.1:{model_port}/v1",
            }
        },
    )
    (source / "config.yaml").write_text(yaml.safe_dump(config.model_dump()))
    with sqlite3.connect(data / "openbot.db") as database:
        database.executescript(SCHEMA_SQL.format(single_user_id=SINGLE_USER_ID))
        database.execute("INSERT INTO schema_version VALUES (11,'2026-10-30T00:00:00Z')")
        database.execute(
            "INSERT INTO conversations(id,title,platform,created_at,updated_at) "
            "VALUES (?,?, 'web',?,?)",
            (
                CONVERSATION_ID,
                "Synthetic imported conversation",
                "2026-10-30T00:00:00Z",
                "2026-10-30T00:00:00Z",
            ),
        )
        database.execute(
            "INSERT INTO messages(id,conversation_id,role,content,timestamp,created_at) "
            "VALUES (?,?,?,?,?,?)",
            (
                "synthetic-old-message",
                CONVERSATION_ID,
                "user",
                "Synthetic imported history",
                "2026-10-30T00:00:00Z",
                "2026-10-30T00:00:00Z",
            ),
        )
        database.execute(
            "INSERT INTO schedules(id,name,prompt,cron,created_at,updated_at) "
            "VALUES ('synthetic-schedule','Synthetic active task','Do not execute',"
            "'* * * * *','now','now')"
        )
    (data / "personal_memory").mkdir()
    (data / "personal_memory/profile.md").write_text(
        "# Synthetic profile\n\nOnly synthetic data.\n"
    )
    return source


def tree_hashes(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


class GateHandler(FakeHandler):
    def do_POST(self) -> None:  # noqa: N802
        if self.server.hold.is_set():
            self.server.observed.set()
            if not self.server.release.wait(10):
                self.send_error(504)
                return
        super().do_POST()


def update_admission(client, model: FakeOpenAI) -> dict:
    lease = secrets.token_hex(32)
    model.hold.set()
    model.release.clear()
    model.observed.clear()
    try:
        response = client.post(
            "/api/chat/runs",
            json={
                "message": "Explain inverse kinematics briefly without using tools.",
                "request_id": secrets.token_hex(16),
                "conversation_id": CONVERSATION_ID,
            },
        )
        response.raise_for_status()
        run = response.json()
        assert model.observed.wait(5), "The running request never reached the local fake model"
        assert client.post("/api/desktop/update/prepare", json={"lease": lease}).status_code == 409
    finally:
        model.hold.clear()
        model.release.set()
    end = time.monotonic() + 10
    while run["status"] not in {"completed", "failed", "cancelled"} and time.monotonic() < end:
        time.sleep(0.05)
        response = client.get("/api/chat/runs/" + run["run_id"])
        response.raise_for_status()
        run = response.json()
    assert run["status"] == "completed", "The blocked fake-model run did not complete"
    client.post("/api/desktop/update/prepare", json={"lease": lease}).raise_for_status()
    assert (
        client.post(
            "/api/chat/runs",
            json={"message": "must-not-execute", "request_id": secrets.token_hex(16)},
        ).status_code
        == 409
    )
    assert client.post("/api/desktop/update/prepare", json={"lease": lease}).status_code == 409
    assert (
        client.post("/api/desktop/update/resume", json={"lease": secrets.token_hex(32)}).status_code
        == 409
    )
    client.post("/api/desktop/update/resume", json={"lease": lease}).raise_for_status()
    chat(client, CONVERSATION_ID)
    return {
        "busy_rejected": True,
        "prepared_blocks_new_chat": True,
        "wrong_lease_rejected": True,
        "resume_accepts_chat": True,
    }


def _log_evidence(root: Path, output: Path) -> int:
    errors = 0
    output.mkdir(parents=True, exist_ok=True)
    for path in root.glob("*.log"):
        content = path.read_text(errors="replace").replace(SYNTHETIC_SECRET, "[synthetic-secret]")
        for line in content.splitlines():
            try:
                record = json.loads(line)
            except ValueError:
                record = {}
            if isinstance(record, dict) and record.get("level") in {"error", "critical"}:
                errors += 1
        errors += evaluate_worker_report({"status": "passed"}, content, 0)["unexpected_error_logs"]
        (output / path.name).write_text(content)
    return errors


def run_worker(args) -> dict:
    resources = args.app.resolve(strict=True) / "Contents/Resources"
    runtime, entry = resources / "runtime", resources / "service_entry.py"
    report = {"mode": "packaged-desktop-workflows-loopback-only", "status": "failed"}
    model = FakeOpenAI()
    model.RequestHandlerClass = GateHandler
    model.hold, model.observed, model.release = (
        threading.Event(),
        threading.Event(),
        threading.Event(),
    )
    model.start()
    try:
        with tempfile.TemporaryDirectory(prefix="openbot-packaged-workflows-") as temporary:
            root = Path(temporary).resolve()
            (root / "entry.py").write_text(
                WRAPPER.replace("audit_synthetic_io(data,", "audit_synthetic_io(data.parent,")
            )
            processes, clients, logs = [], [], []

            def launch(label):
                process, log, client = start(root, label, runtime=runtime, entry=entry)
                processes.append(process)
                clients.append(client)
                logs.append(log)
                return process, client

            try:
                source = synthetic_deployment(root, model.server_port)
                original = tree_hashes(source)
                process, client = launch("import-before")
                initial = client.get("/api/desktop/status").json()
                assert not initial["configured"]
                preview = client.post(
                    "/api/desktop/import/preview",
                    json={"source_dir": str(source), "acknowledgement": "source-stopped"},
                )
                if preview.status_code != 200:
                    raise RuntimeError(
                        "Real offline-import preview/lsof failed: " + preview.text[:400]
                    )
                response = client.post(
                    "/api/desktop/import/confirm",
                    json={
                        "preview_id": preview.json()["preview_id"],
                        "acknowledgement": "copy-and-pause",
                    },
                )
                response.raise_for_status()
                assert response.json()["status"] == "staged" and process.wait(10) == 75
                process, client = launch("import-after")
                status = client.get("/api/desktop/status").json()
                assert status["configured"] and status["import_result"] == {"status": "imported"}
                assert status["work_dir"] == initial["work_dir"] and not any(
                    status["permissions"].values()
                )
                assert tree_hashes(source) == original
                data = root / "application/data"
                assert (data / "personal_memory/profile.md").read_bytes() == (
                    source / "data/personal_memory/profile.md"
                ).read_bytes()
                with sqlite3.connect(f"file:{data / 'openbot.db'}?mode=ro", uri=True) as database:
                    assert (
                        database.execute("SELECT status FROM schedules").fetchone()[0] == "paused"
                    )
                history = client.get("/api/conversations/" + CONVERSATION_ID)
                history.raise_for_status()
                assert history.json()["messages"][0]["content"] == "Synthetic imported history"
                assert chat(client, CONVERSATION_ID)["conversation_id"] == CONVERSATION_ID
                services = client.get("/api/desktop/services").json()
                assert all(
                    not services["configuration"][name]["enabled"]
                    for name in ("telegram", "feishu", "wechat")
                )
                services["configuration"]["model"]["max_retries"] = 2
                client.put(
                    "/api/desktop/services",
                    json={
                        "configuration": services["configuration"],
                        "secrets": {"tavily.api_key": SYNTHETIC_SECRET},
                    },
                ).raise_for_status()
                assert process.wait(10) == 75
                process, client = launch("services-after")
                response = client.get("/api/desktop/services")
                response.raise_for_status()
                services = response.json()
                assert services["configuration"]["model"]["max_retries"] == 2
                assert next(
                    item for item in services["secrets"] if item["key"] == "tavily.api_key"
                )["is_set"]
                for endpoint in ("/api/desktop/services", "/api/settings", "/api/settings/secrets"):
                    response = client.get(endpoint)
                    response.raise_for_status()
                    assert SYNTHETIC_SECRET not in response.text
                assert client.get("/api/settings").json()["model"]["max_retries"] == 2
                report["update_admission"] = update_admission(client, model)
                stop(process)
                assert process.returncode == 0 and tree_hashes(source) == original
                report.update(
                    status="passed",
                    real_lsof_checked=True,
                    import_restart_exit=75,
                    import_result="imported",
                    source_unchanged=True,
                    imported_history_resumed=True,
                    markdown_copied=True,
                    schedules_paused=True,
                    channels_disabled=True,
                    execution_grants_cleared=True,
                    work_dir_preserved=True,
                    settings_restart_exit=75,
                    services_runtime_effective=True,
                    secret_presence_only=True,
                    local_fake_requests=model.requests,
                    shutdown_exit=0,
                )
            finally:
                model.hold.clear()
                model.release.set()
                for process in processes:
                    stop(process)
                for client in clients:
                    client.close()
                for log in logs:
                    log.close()
                report["error_log_lines"] = _log_evidence(
                    root, args.report.parent / (args.report.stem + "-logs")
                )
                if report["error_log_lines"]:
                    report["status"] = "failed"
    except BaseException as exc:
        report["status"] = "failed"
        report["error_type"] = type(exc).__name__
        report["error"] = str(exc)[:500].replace(SYNTHETIC_SECRET, "[synthetic-secret]")
    finally:
        model.stop()
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", type=Path, required=True)
    parser.add_argument(
        "--report", type=Path, default=Path("/private/tmp/openbot-desktop-workflows.json")
    )
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        report = run_worker(args)
        print(json.dumps(report))
        raise SystemExit(0 if report["status"] == "passed" else 1)
    process = subprocess.Popen(
        [
            sys.executable,
            "-I",
            "-B",
            str(Path(__file__).resolve()),
            "--worker",
            "--app",
            str(args.app),
            "--report",
            str(args.report),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    try:
        output, _ = process.communicate(timeout=60)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGTERM)
        try:
            output, _ = process.communicate(timeout=3)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            output, _ = process.communicate(timeout=3)
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(
            json.dumps(
                {"status": "failed", "error_type": "TimeoutError", "controller_timeout_seconds": 60}
            )
            + "\n"
        )
        print(output.decode(errors="replace"))
        raise SystemExit(1) from None
    print(output.decode(errors="replace"), end="")
    raise SystemExit(process.returncode)


if __name__ == "__main__":
    main()
