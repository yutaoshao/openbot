"""OpenBot application entrypoint."""

from __future__ import annotations

import contextlib
import os
import sys

from src.application import Application
from src.core.config import load_config
from src.core.logging import setup_logging
from src.core.trace import setup_tracing

__all__ = ["Application", "main"]


def _restart_current_process() -> None:
    """Re-exec the current Python entrypoint with the existing argv/env."""
    os.execvpe(sys.executable, [sys.executable, *sys.argv], os.environ.copy())


def main() -> None:
    """Application entrypoint."""
    config = load_config()
    setup_logging(
        level=config.log.level,
        fmt=config.log.format,
        log_file=config.log.file,
        max_bytes=config.log.max_bytes,
        backup_count=config.log.backup_count,
    )
    if config.log.otlp_endpoint:
        setup_tracing(
            service_name="openbot",
            otlp_endpoint=config.log.otlp_endpoint,
        )
    app = Application()
    with contextlib.suppress(KeyboardInterrupt):
        import asyncio

        asyncio.run(app.run_forever())
    if app.restart_requested:
        _restart_current_process()


if __name__ == "__main__":
    main()
