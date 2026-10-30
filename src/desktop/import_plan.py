"""Validate and stage offline imports; no live database is ever replaced here."""

from __future__ import annotations

import re
import secrets
import shutil
import sqlite3
import stat
import time
from contextlib import closing
from pathlib import Path

import sqlite_vec
import yaml
from dotenv import dotenv_values

from src.desktop.import_publish import IMPORT_DIRECTORY
from src.desktop.import_source import (
    ImportRejected,
    assert_stopped,
    fingerprint,
    import_config,
    readonly_database,
    schema_version,
    source_files,
)
from src.desktop.settings import (
    DesktopSettings,
    write_private_json,
    write_private_text,
)

# Startup emits logs/metrics before onboarding. They are operational telemetry,
# unlike memory/delivery records; new business tables are protected by default.
INITIALIZATION_TABLES = frozenset({"schema_version", "logs", "metrics"})


def _quoted_identifier(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _business_table_names(database: sqlite3.Connection) -> list[str]:
    """Discover logical tables, including vectors without counting empty index metadata.

    Some vec0 backing tables are reported as ordinary tables by SQLite. Rebuild
    only virtual-table declarations in an isolated empty connection to discover
    their generated backing names instead of hard-coding suffixes or business
    table names. The trusted bundled extension is the only external module loaded.
    """
    database.enable_load_extension(True)
    try:
        sqlite_vec.load(database)
    finally:
        database.enable_load_extension(False)
    tables = database.execute("PRAGMA main.table_list").fetchall()
    backing: set[str] = set()
    with closing(sqlite3.connect(":memory:")) as empty:
        empty.enable_load_extension(True)
        try:
            sqlite_vec.load(empty)
        finally:
            empty.enable_load_extension(False)
        for schema, name, kind, *_ in tables:
            if schema != "main" or kind != "virtual":
                continue
            declaration = database.execute(
                "SELECT sql FROM main.sqlite_master WHERE type='table' AND name=?", (name,)
            ).fetchone()[0]
            before = {row[1] for row in empty.execute("PRAGMA main.table_list")}
            empty.execute(declaration)
            after = {row[1] for row in empty.execute("PRAGMA main.table_list")}
            backing.update(after - before - {name})
    return [
        name
        for schema, name, kind, *_ in tables
        if schema == "main"
        and kind in {"table", "virtual"}
        and not name.startswith("sqlite_")
        and name not in INITIALIZATION_TABLES
        and name not in backing
    ]


WARNINGS = [
    "旧实例必须已退出；导入保留源数据，不自动接管原渠道。",
    "所有渠道与定时任务暂停；Shell/Python 授权清空。",
    "保留当前工作目录；不复制旧源码、workspace、日志及缓存。",
    "只支持标准 data/ 布局；导入后仍需确认外部服务配置。",
]


def ensure_empty(settings: DesktopSettings) -> None:
    if settings.read().configured:
        raise ImportRejected("当前实例已经配置，请使用全新应用数据目录导入，不能覆盖或合并。")
    data = settings.data_dir / "data"
    database_path = data / "openbot.db"
    _assert_no_unowned_files(data, database_path.exists())
    if database_path.exists():
        with readonly_database(database_path) as database:
            try:
                for table in _business_table_names(database):
                    if database.execute(
                        f"SELECT 1 FROM {_quoted_identifier(table)} LIMIT 1"
                    ).fetchone():
                        raise ImportRejected("当前实例已有业务数据，不能覆盖或合并。")
            except sqlite3.Error as exc:
                raise ImportRejected("无法确认当前数据库为空，不能覆盖或合并。") from exc


def _assert_no_unowned_files(data: Path, has_database: bool) -> None:
    """Only the initialized database and fixed startup logs are replaceable.

    Check links and special files before opening the database or following any
    directory; unknown files remain user data even when currently zero bytes.
    """
    if data.is_symlink() or (data.exists() and not data.is_dir()):
        raise ImportRejected("当前数据目录包含链接或特殊项，不能覆盖或合并。")
    if not data.exists():
        return
    database_files = {Path("openbot.db"), Path("openbot.db-wal"), Path("openbot.db-shm")}
    for path in data.rglob("*"):
        mode = path.lstat().st_mode
        if stat.S_ISDIR(mode):
            continue
        if not stat.S_ISREG(mode):
            raise ImportRejected("当前数据目录包含链接或特殊项，不能覆盖或合并。")
        relative = path.relative_to(data)
        if has_database and relative in database_files:
            continue
        if relative.parent == Path("logs") and re.fullmatch(
            r"openbot\.log(?:\.[1-5])?", relative.name
        ):
            continue
        raise ImportRejected("当前实例已有本地数据，不能覆盖或合并。")


class OfflineImporter:
    def __init__(self, settings: DesktopSettings) -> None:
        self.settings = settings
        self.plans: dict[str, dict] = {}

    def preview(self, directory: str) -> dict:
        ensure_empty(self.settings)
        source = Path(directory)
        files = source_files(source, self.settings.data_dir)
        source = source.resolve()
        assert_stopped(files)
        import_config(source)
        version = schema_version(source / "data/openbot.db")
        hashes = fingerprint(source, files)
        identifier = secrets.token_urlsafe(24)
        expiry = time.time() + 600
        self.plans = {identifier: {"source": source, "hashes": hashes, "expires": expiry}}
        return {
            "preview_id": identifier,
            "source_dir": str(source),
            "schema_version": version,
            "files": [
                {"path": str(p.relative_to(source)), "bytes": p.stat().st_size} for p in files
            ],
            "warnings": WARNINGS,
            "expires_at": expiry,
        }

    def stage(self, identifier: str) -> None:
        plan = self.plans.pop(identifier, None)
        if plan is None or plan["expires"] < time.time():
            raise ImportRejected("预览已过期或已使用，请重新预览。")
        ensure_empty(self.settings)
        source = plan["source"]
        files = source_files(source, self.settings.data_dir)
        assert_stopped(files)
        if fingerprint(source, files) != plan["hashes"]:
            raise ImportRejected("预览后源数据已变化，请确认旧实例退出并重新预览。")
        pending = self.settings.data_dir / IMPORT_DIRECTORY
        if pending.exists():
            raise ImportRejected("已有导入暂存数据，请先重新启动应用以处理上次导入。")
        pending.mkdir(mode=0o700)
        try:
            self._copy(source, files, pending)
            current = source_files(source, self.settings.data_dir)
            assert_stopped(current)
            if fingerprint(source, current) != plan["hashes"]:
                raise ImportRejected("复制期间源数据发生变化，导入未生效。")
            write_private_json(
                pending / "ready.json",
                {"version": 1, "paths": ["data", "config.yaml", "desktop-state.json"]},
            )
        except BaseException:
            # Preserve generated staging for diagnosis; never remove source/target data.
            pending.rename(self.settings.data_dir / ("import-rejected-" + secrets.token_hex(6)))
            raise

    def abandon(self) -> None:
        pending = self.settings.data_dir / IMPORT_DIRECTORY
        if pending.exists():
            pending.rename(self.settings.data_dir / ("import-abandoned-" + secrets.token_hex(6)))

    def _copy(self, source: Path, files: list[Path], pending: Path) -> None:
        data = pending / "data"
        data.mkdir(mode=0o700)
        with (
            readonly_database(source / "data/openbot.db", immutable=True) as original,
            closing(sqlite3.connect(data / "openbot.db")) as copied,
        ):
            original.backup(copied)
            copied.execute("UPDATE schedules SET status='paused'")
            copied.commit()
        (data / "openbot.db").chmod(0o600)
        for path in files:
            relative = path.relative_to(source)
            if relative.parts[0] != "data" or relative in {
                Path("data/openbot.db"),
                Path("data/openbot.db-wal"),
                Path("data/openbot.db-shm"),
            }:
                continue
            target = pending / relative
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            shutil.copyfile(path, target)
            target.chmod(0o600)
        self._configuration(source, pending)

    def _configuration(self, source: Path, pending: Path) -> None:
        config = import_config(source)
        values = config.model_dump()
        for channel in ("telegram", "feishu", "wechat"):
            values[channel]["enabled"] = False
        values["storage"]["db_path"] = "data/openbot.db"
        values["wechat"]["state_path"] = "data/wechat/ilink_state.json"
        values["log"]["file"] = "data/logs/openbot.log"
        values["log"]["otlp_endpoint"] = None
        values["agent"]["system_prompt"] = config.agent.system_prompt
        from src.desktop.services import imported_service_state

        env_path = source / ".env"
        env_values = dotenv_values(env_path, interpolate=False) if env_path.exists() else {}
        allowed = {
            key: value
            for key, value in env_values.items()
            if re.fullmatch(r"[A-Z][A-Z0-9_]{0,127}", key)
            and not key.startswith(("PYTHON", "DYLD", "LD_"))
            and key not in {"PATH", "HOME", "TMPDIR", "SHELL", "LANG", "LC_CTYPE"}
        }
        state = imported_service_state(config, allowed, self.settings.read())
        values.update(state.services)
        write_private_json(pending / "desktop-state.json", state.model_dump())
        write_private_text(
            pending / "config.yaml", yaml.safe_dump(values, allow_unicode=True, sort_keys=False)
        )
