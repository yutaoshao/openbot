"""Run the shared application under a native parent's explicit ownership."""

from __future__ import annotations

import asyncio
import contextlib
import fcntl
import os
import re
import signal
import socket
import sys
from pathlib import Path

import yaml

from src.application import Application
from src.application.runtime import RuntimeEnvironment
from src.core.config import AppConfig
from src.core.logging import setup_logging
from src.desktop.import_publish import apply_pending_import
from src.desktop.service import DesktopService
from src.desktop.settings import DesktopSettings, write_private_json, write_private_text

RESTART_EXIT_CODE = 75


def _credentials() -> tuple[str, str]:
    token = os.environ.pop("OPENBOT_DESKTOP_TOKEN", "")
    instance_id = os.environ.pop("OPENBOT_DESKTOP_INSTANCE_ID", "")
    if len(token) < 32 or not re.fullmatch(r"[A-Za-z0-9_-]{16,128}", instance_id):
        raise ValueError("Native desktop instance credentials are missing or invalid.")
    return token, instance_id


def _load_config(path: Path) -> AppConfig:
    if not path.exists():
        config = AppConfig(telegram={"enabled": False})
        write_private_text(path, yaml.safe_dump(config.model_dump(), sort_keys=False))
        return config
    return AppConfig.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")) or {})


def _bind_loopback() -> socket.socket:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        listener.bind(("127.0.0.1", 0))
        listener.listen(128)
        listener.setblocking(False)
        return listener
    except BaseException:
        listener.close()
        raise


def _parent_control(app: Application) -> None:
    """Read only the parent's pipe, without an executor thread that can block exit."""
    loop = asyncio.get_running_loop()
    descriptor = sys.stdin.fileno()
    pending = bytearray()

    def readable() -> None:
        chunk = os.read(descriptor, 1024)
        if not chunk:
            app._shutdown_event.set()
            loop.remove_reader(descriptor)
            return
        pending.extend(chunk)
        while b"\n" in pending:
            line, _, remainder = pending.partition(b"\n")
            pending[:] = remainder
            if line == b"shutdown":
                app._shutdown_event.set()
        if len(pending) > 4096:
            app._shutdown_event.set()

    loop.add_reader(descriptor, readable)


async def _serve(app: Application, ready_file: Path, instance_id: str, port: int) -> int:
    loop = asyncio.get_running_loop()
    wait_for_shutdown: asyncio.Task | None = None
    started = False
    try:
        await app.start()
        started = True
        _parent_control(app)
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, app._shutdown_event.set)
        write_private_json(
            ready_file,
            {"protocol_version": 1, "instance_id": instance_id, "pid": os.getpid(), "port": port},
        )
        wait_for_shutdown = asyncio.create_task(app._shutdown_event.wait())
        finished, _ = await asyncio.wait(
            [wait_for_shutdown, app.api_task], return_when=asyncio.FIRST_COMPLETED
        )
        if app.api_task in finished and not app._shutdown_event.is_set():
            await app.api_task
            raise RuntimeError("The desktop API exited unexpectedly.")
        return RESTART_EXIT_CODE if app.restart_requested else 0
    finally:
        if wait_for_shutdown:
            wait_for_shutdown.cancel()
            await asyncio.gather(wait_for_shutdown, return_exceptions=True)
        loop.remove_reader(sys.stdin.fileno())
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.remove_signal_handler(sig)
        ready_file.unlink(missing_ok=True)
        if started:
            await app.stop()


def _build_application(
    settings: DesktopSettings, runtime: Path, listener: socket.socket, token: str
) -> Application:
    state = settings.read()
    config_path = settings.data_dir / "config.yaml"
    config = settings.prepare_config(_load_config(config_path), listener.getsockname()[1], runtime)
    settings.install_model_key()
    setup_logging(
        level=config.log.level,
        fmt="json",
        log_file=config.log.file,
        max_bytes=config.log.max_bytes,
        backup_count=config.log.backup_count,
    )
    service = DesktopService(settings, token=token, runtime=runtime)
    workspace = Path(state.work_dir)
    if not workspace.is_dir():
        raise ValueError("已配置的工作目录不存在，请恢复目录后重试。")
    return Application(
        RuntimeEnvironment(
            config_path=config_path,
            config=config,
            work_dir=workspace,
            data_root=settings.data_dir / "data",
            snapshot_root=settings.data_dir / "data" / "file_snapshots",
            skills_dirs=(
                workspace / ".claude" / "skills",
                workspace / ".agents" / "skills",
                settings.data_dir / "data" / "skills",
            ),
            api_socket=listener,
            configure_api=service.install_api,
        )
    )


def run(data_dir: Path, ready_file: Path, runtime: Path) -> int:
    token, instance_id = _credentials()
    settings = DesktopSettings(data_dir)
    if ready_file.parent.resolve() != (settings.data_dir / "run").resolve():
        raise ValueError("The readiness file must be inside the owned data directory's run folder.")
    ready_file.parent.mkdir(mode=0o700, exist_ok=True)
    descriptor = os.open(settings.data_dir / "python-service.lock", os.O_CREAT | os.O_RDWR, 0o600)
    previous_mask = os.umask(0o077)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("OpenBot already owns this desktop data directory.") from exc
        apply_pending_import(settings)
        os.environ["PYTHON_DOTENV_DISABLED"] = "1"
        os.environ["PATH"] = f"{runtime / 'bin'}:/usr/bin:/bin:/usr/sbin:/sbin"
        os.chdir(settings.data_dir)
        with _bind_loopback() as listener:
            app = _build_application(settings, runtime, listener, token)
            with contextlib.suppress(KeyboardInterrupt):
                return asyncio.run(_serve(app, ready_file, instance_id, listener.getsockname()[1]))
        return 0
    finally:
        os.close(descriptor)
        os.umask(previous_mask)
