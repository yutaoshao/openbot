"""Read a user-selected, stopped standard deployment without executing its config."""

from __future__ import annotations

import hashlib
import sqlite3
import subprocess
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import quote

if TYPE_CHECKING:
    from collections.abc import Iterator

import yaml

from src.core.config import AppConfig

DATA_ITEMS = (
    "openbot.db",
    "conversations",
    "personal_memory",
    "skills",
    "file_snapshots",
    "wechat",
)
MAX_FILES = 20000
MAX_BYTES = 2 * 1024**3


class ImportRejected(ValueError):  # noqa: N818
    """A source or destination cannot be safely imported."""


@contextmanager
def readonly_database(path: Path, *, immutable: bool = False) -> Iterator[sqlite3.Connection]:
    suffix = "&immutable=1" if immutable else ""
    database = sqlite3.connect(f"file:{quote(str(path))}?mode=ro{suffix}", uri=True, timeout=1)
    try:
        yield database
    finally:
        database.close()


def schema_version(path: Path) -> int:
    try:
        with readonly_database(path, immutable=True) as database:
            version = database.execute("SELECT MAX(version) FROM schema_version").fetchone()[0]
            required = {"conversations", "messages", "knowledge", "schedules"}
            tables = {
                r[0] for r in database.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            if version != 11 or not required <= tables:
                raise ImportRejected("目前仅支持 schema 11 的标准 OpenBot 数据，请先升级旧部署。")
            return version
    except sqlite3.Error as exc:
        raise ImportRejected("源数据库无法读取或不是受支持的 OpenBot 数据库。") from exc


def assert_stopped(files: list[Path]) -> None:
    # lsof is an independent guard; a successful SQLite read alone does not prove stop.
    try:
        result = subprocess.run(
            ["/usr/sbin/lsof", "-t", "--", *map(str, files)],
            capture_output=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ImportRejected("无法检查源目录占用情况，请确认旧实例已退出后重试。") from exc
    if result.returncode != 1 or result.stdout.strip() or result.stderr.strip():
        raise ImportRejected("源数据仍被进程打开，或占用检查失败；请退出旧实例后重试。")


def source_files(source: Path, destination: Path) -> list[Path]:
    if not source.is_absolute() or source.is_symlink() or not source.is_dir():
        raise ImportRejected("请选择旧部署的绝对目录路径，不支持符号链接。")
    root = source.resolve()
    target = destination.resolve()
    if root == target or root in target.parents or target in root.parents:
        raise ImportRejected("源目录与应用数据目录不能相同或互相包含。")
    paths = [root / "config.yaml"]
    if (root / ".env").exists() or (root / ".env").is_symlink():
        paths.append(root / ".env")
    data = root / "data"
    if data.is_symlink() or not data.is_dir():
        raise ImportRejected("只支持包含 config.yaml 和 data/ 的标准部署目录。")
    for name in DATA_ITEMS:
        entry = data / name
        if entry.is_symlink():
            raise ImportRejected("导入范围包含符号链接，请先导出普通文件。")
        if entry.is_dir():
            for child in entry.rglob("*"):
                if child.is_symlink() or (not child.is_file() and not child.is_dir()):
                    raise ImportRejected("导入范围包含链接或特殊文件。")
                if child.is_file():
                    paths.append(child)
        elif entry.exists():
            paths.append(entry)
    wal = data / "openbot.db-wal"
    if wal.exists() and wal.stat().st_size:
        raise ImportRejected(
            "源数据库仍有未检查点的 WAL，请正常退出旧实例并完成数据库检查点后重试。"
        )
    # WAL is part of the consistency fingerprint, but is not copied alongside backup.
    paths.extend(
        path for path in (data / "openbot.db-wal", data / "openbot.db-shm") if path.exists()
    )
    if any(path.is_symlink() or not path.is_file() for path in paths):
        raise ImportRejected("导入所需文件缺失、不是普通文件或包含链接。")
    if len(paths) > MAX_FILES or sum(path.stat().st_size for path in paths) > MAX_BYTES:
        raise ImportRejected("导入数据超过 20000 个文件或 2 GiB，请先整理旧部署。")
    if data / "openbot.db" not in paths:
        raise ImportRejected("未找到 data/openbot.db。")
    return sorted(paths)


def fingerprint(source: Path, files: list[Path]) -> dict[str, str]:
    result = {}
    for path in files:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        result[str(path.relative_to(source))] = digest.hexdigest()
    return result


def import_config(source: Path) -> AppConfig:
    try:
        value = yaml.safe_load((source / "config.yaml").read_text(encoding="utf-8"))
        config = AppConfig.model_validate(value)
    except Exception as exc:
        raise ImportRejected("旧配置无效，请先在旧部署检查 config.yaml。") from exc
    if Path(config.storage.db_path) != Path("data/openbot.db"):
        raise ImportRejected("暂不支持自定义数据库路径，请先导出为标准部署目录。")
    if Path(config.wechat.state_path) != Path("data/wechat/ilink_state.json"):
        raise ImportRejected("暂不支持自定义微信状态路径，请先导出为标准部署目录。")
    return config
