"""Explicit process resources for an embedded OpenBot application."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import socket
    from collections.abc import Callable

    from fastapi import FastAPI

    from src.core.config import AppConfig


@dataclass(frozen=True)
class RuntimeEnvironment:
    """Separate persistent application data from the tools' working directory."""

    config_path: Path = Path("config.yaml")
    config: AppConfig | None = None
    work_dir: Path = Path(".")
    data_root: Path = Path("data")
    snapshot_root: Path | None = None
    skills_dirs: tuple[Path, ...] | None = None
    api_socket: socket.socket | None = None
    configure_api: Callable[[FastAPI], None] | None = None
