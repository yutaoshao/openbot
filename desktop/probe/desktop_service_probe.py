"""Exercise the packaged desktop entrypoint with synthetic data and a loopback model."""

from __future__ import annotations

import argparse
import asyncio
import json
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

PROBE_DIRECTORY = Path(__file__).resolve().parent
sys.path.insert(0, str(PROBE_DIRECTORY))
from service_fake import REPLY, FakeOpenAI  # noqa: E402

WRAPPER = """import runpy
import sys
from pathlib import Path
probe, data, ready, runtime, entry = (Path(value).resolve() for value in sys.argv[1:])
sys.path.insert(0, str(probe))
from service_guard import audit_synthetic_io, verify_dotenv_disabled
verify_dotenv_disabled()
sys.addaudithook(lambda event, args: audit_synthetic_io(data, event, args))
sys.argv = [str(entry), '--data-dir', str(data), '--ready-file', str(ready),
            '--resource-dir', str(runtime)]
runpy.run_path(str(entry), run_name='__main__')
"""


def start(root, label, *, runtime, entry):
    data = root / "application"
    ready = data / "run" / f"{label}.json"
    token = secrets.token_hex(32)
    identifier = secrets.token_hex(32)
    log = (root / f"{label}.log").open("w")
    environment = {
        "PATH": "/usr/bin:/bin",
        "PYTHON_DOTENV_DISABLED": "1",
        "TIKTOKEN_CACHE_DIR": str(runtime / "tokenizer-cache"),
        "OPENBOT_DESKTOP_TOKEN": token,
        "OPENBOT_DESKTOP_INSTANCE_ID": identifier,
        "TMPDIR": str(root),
    }
    process = subprocess.Popen(
        [
            str(runtime / "bin/python3"),
            "-I",
            "-B",
            str(root / "entry.py"),
            str(PROBE_DIRECTORY),
            str(data),
            str(ready),
            str(runtime),
            str(entry),
        ],
        stdin=subprocess.PIPE,
        stdout=log,
        stderr=subprocess.STDOUT,
        env=environment,
        cwd=root,
    )
    end = time.monotonic() + 15
    while time.monotonic() < end:
        if process.poll() is not None:
            log.close()
            raise RuntimeError(
                f"{label} exited {process.returncode}: "
                + (root / f"{label}.log").read_text()[-7000:]
            )
        if ready.exists():
            value = json.loads(ready.read_text())
            assert value["instance_id"] == identifier and value["pid"] == process.pid
            assert value["protocol_version"] == 1 and value["port"] > 0
            return (
                process,
                log,
                httpx.Client(
                    base_url=f"http://127.0.0.1:{value['port']}",
                    headers={"Authorization": f"Bearer {token}"},
                    trust_env=False,
                    timeout=5,
                ),
            )
        time.sleep(0.05)
    process.kill()
    process.wait(5)
    log.close()
    raise TimeoutError(f"{label} did not produce readiness")


def stop(process):
    if process.poll() is None:
        try:
            process.stdin.write(b"shutdown\n")
            process.stdin.flush()
            process.wait(10)
        except BaseException:
            process.kill()
            process.wait(5)
            raise


def chat(client, conversation_id=None):
    payload = {
        "message": "Explain inverse kinematics briefly without using tools.",
        "request_id": secrets.token_hex(16),
    }
    if conversation_id:
        payload["conversation_id"] = conversation_id
    response = client.post("/api/chat/runs", json=payload)
    response.raise_for_status()
    run = response.json()
    end = time.monotonic() + 20
    while run["status"] not in {"completed", "cancelled", "failed"} and time.monotonic() < end:
        time.sleep(0.05)
        response = client.get("/api/chat/runs/" + run["run_id"])
        response.raise_for_status()
        run = response.json()
    assert run["status"] == "completed", run
    assert run["text"] == REPLY, run
    return run


async def websocket_chat(client, conversation_id):
    from websockets.asyncio.client import connect

    base = str(client.base_url).rstrip("/")
    token = client.headers["Authorization"].removeprefix("Bearer ")
    endpoint = base.replace("http://", "ws://") + "/api/ws/chat?conversation_id=" + conversation_id
    async with connect(
        endpoint, origin=base, subprotocols=["openbot.auth." + token], proxy=None
    ) as websocket:
        connected = json.loads(await asyncio.wait_for(websocket.recv(), 5))
        assert connected["type"] == "connected"
        await websocket.send(
            json.dumps({"message": "Explain inverse kinematics briefly without using tools."})
        )
        text = ""
        for _ in range(100):
            value = json.loads(await asyncio.wait_for(websocket.recv(), 15))
            if value.get("chunk_type") == "text":
                text += value.get("text", "")
            if value.get("chunk_type") == "done" or value.get("type") == "message":
                text = value.get("text", text) if value.get("type") == "message" else text
                assert text == REPLY, value
                return
        raise AssertionError("WebSocket did not report a terminal event")


def main():
    parser = argparse.ArgumentParser(
        description="Synthetic packaged desktop service integration probe"
    )
    parser.add_argument("--app", type=Path, required=True)
    parser.add_argument(
        "--report", type=Path, default=Path("/private/tmp/openbot-desktop-live-probe.json")
    )
    args = parser.parse_args()
    resources = args.app.resolve(strict=True) / "Contents" / "Resources"
    runtime, entry = resources / "runtime", resources / "service_entry.py"
    if not (runtime / "bin/python3").is_file() or not entry.is_file():
        parser.error("The app does not contain the desktop service and standalone runtime.")
    report = {"mode": "packaged-desktop-service-loopback-probe", "status": "failed"}
    evidence = args.report.parent / (args.report.stem + "-logs")
    evidence.mkdir(parents=True, exist_ok=True)
    model = FakeOpenAI()
    model.start()
    try:
        with tempfile.TemporaryDirectory(prefix="openbot-packaged-desktop-") as directory:
            root = Path(directory).resolve()
            (root / "entry.py").write_text(WRAPPER)
            processes, clients, logs = [], [], []
            try:
                p, log, client = start(root, "first", runtime=runtime, entry=entry)
                processes.append(p)
                clients.append(client)
                logs.append(log)
                initial_response = client.get("/api/desktop/status")
                initial_response.raise_for_status()
                initial = initial_response.json()
                assert not initial["configured"] and not any(initial["permissions"].values())
                assert (
                    client.get(
                        "/health", headers={"Authorization": "Bearer wrong-instance"}
                    ).status_code
                    == 401
                )
                validation = client.post("/api/desktop/browser-session")
                validation.raise_for_status()
                assert "set-cookie" not in validation.headers
                response = client.post(
                    "/api/desktop/setup",
                    json={
                        "model": {
                            "provider": "openai_compatible",
                            "base_url": f"http://127.0.0.1:{model.server_port}/v1",
                            "model": "openbot-service-probe",
                        },
                        "work_dir": initial["work_dir"],
                    },
                )
                response.raise_for_status()
                assert response.json()["requires_restart"] and p.wait(15) == 75
                p, log, client = start(root, "second", runtime=runtime, entry=entry)
                processes.append(p)
                clients.append(client)
                logs.append(log)
                assert client.get("/api/desktop/status").json()["configured"]
                withdrawn = secrets.token_hex(16)
                rejection = client.post("/api/chat/requests/" + withdrawn + "/stop")
                rejection.raise_for_status()
                assert rejection.json()["status"] == "not_accepted"
                assert (
                    client.post(
                        "/api/chat/runs", json={"message": "late", "request_id": withdrawn}
                    ).status_code
                    == 409
                )
                first = chat(client)
                second = chat(client, first["conversation_id"])
                assert first["conversation_id"] == second["conversation_id"]
                asyncio.run(websocket_chat(client, first["conversation_id"]))
                history = client.get("/api/conversations/" + first["conversation_id"])
                history.raise_for_status()
                count = len(history.json()["messages"])
                assert count >= 6, history.json()
                status = client.get("/api/desktop/status").json()
                assert status["data_dir"] != status["work_dir"]
                stop(p)
                assert p.returncode == 0
                report.update(
                    status="passed",
                    first_start_unconfigured=True,
                    model_setup_exit_code=75,
                    authenticated_loopback=True,
                    no_browser_cookie=True,
                    request_withdrawal_prevents_late_submission=True,
                    resumed_same_conversation=True,
                    websocket_subprotocol_authenticated=True,
                    persisted_messages=count,
                    local_fake_model_requests=model.requests,
                    shutdown_exit_code=p.returncode,
                    separate_workspace_and_data=True,
                )
            finally:
                for process in processes:
                    stop(process)
                for client in clients:
                    client.close()
                for log in logs:
                    log.close()
                for path in root.glob("*.log"):
                    shutil.copy2(path, evidence / path.name)
    except BaseException as exc:
        report["error_type"] = type(exc).__name__
        raise
    finally:
        model.stop()
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report))


if __name__ == "__main__":
    main()
