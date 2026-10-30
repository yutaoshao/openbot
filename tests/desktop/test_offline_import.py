"""Offline import consistency, conflict and recovery contracts on synthetic deployments."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
import yaml

from src.core.config import AppConfig
from src.desktop.import_plan import OfflineImporter
from src.desktop.import_publish import apply_pending_import
from src.desktop.import_source import ImportRejected
from src.desktop.settings import DesktopSettings
from src.infrastructure.database_schema import SCHEMA_SQL


@pytest.fixture
def deployment(tmp_path, monkeypatch):
    source = tmp_path / "old"
    source.mkdir()
    (source / "data").mkdir()
    config = AppConfig(
        telegram={"enabled": False},
        model={
            "primary": {
                "provider": "openai_compatible",
                "model": "synthetic",
                "base_url": "http://127.0.0.1:9999/v1",
            }
        },
    )
    (source / "config.yaml").write_text(yaml.safe_dump(config.model_dump()))
    with sqlite3.connect(source / "data/openbot.db") as database:
        database.executescript(SCHEMA_SQL.format(single_user_id="local"))
        database.execute("INSERT INTO schema_version VALUES (11,'now')")
        database.execute(
            "INSERT INTO schedules (id,name,prompt,cron,created_at,updated_at) "
            "VALUES ('1','synthetic','hello','* * * * *','now','now')"
        )
    (source / "data/personal_memory").mkdir()
    (source / "data/personal_memory/profile.md").write_text("合成档案")
    settings = DesktopSettings(tmp_path / "new")
    monkeypatch.setattr("src.desktop.import_plan.assert_stopped", lambda _: None)
    return source, settings, OfflineImporter(settings)


def test_copy_publish_preserves_source_pauses_schedules_and_workspace(deployment):
    source, settings, importer = deployment
    original = (source / "data/openbot.db").read_bytes()
    workspace = settings.read().work_dir
    preview = importer.preview(str(source))
    importer.stage(preview["preview_id"])
    assert not (settings.data_dir / "data/openbot.db").exists()
    assert apply_pending_import(settings)
    assert (source / "data/openbot.db").read_bytes() == original
    assert settings.read().work_dir == workspace
    assert not any(settings.read().permissions.values())
    with sqlite3.connect(settings.data_dir / "data/openbot.db") as copied:
        assert copied.execute("SELECT status FROM schedules").fetchone()[0] == "paused"
    assert (settings.data_dir / "data/personal_memory/profile.md").read_text() == "合成档案"
    assert not apply_pending_import(settings)


def test_source_change_invalidates_preview(deployment):
    source, _, importer = deployment
    preview = importer.preview(str(source))
    (source / "data/personal_memory/profile.md").write_text("changed")
    with pytest.raises(ImportRejected, match="变化"):
        importer.stage(preview["preview_id"])


def test_preview_is_single_use(deployment):
    source, _, importer = deployment
    preview = importer.preview(str(source))
    importer.stage(preview["preview_id"])
    with pytest.raises(ImportRejected, match="已使用"):
        importer.stage(preview["preview_id"])


def test_new_source_file_invalidates_preview(deployment):
    source, _, importer = deployment
    preview = importer.preview(str(source))
    (source / "data/personal_memory/new.md").write_text("changed")
    with pytest.raises(ImportRejected, match="变化"):
        importer.stage(preview["preview_id"])


def test_symlink_rejected(deployment, tmp_path):
    source, _, importer = deployment
    outside = tmp_path / "outside"
    outside.write_text("secret")
    (source / "data/personal_memory/link").symlink_to(outside)
    with pytest.raises(ImportRejected, match="链接"):
        importer.preview(str(source))


def test_nested_destination_rejected(deployment):
    source, _, _ = deployment
    importer = OfflineImporter(DesktopSettings(source / "nested"))
    with pytest.raises(ImportRejected, match="包含"):
        importer.preview(str(source))


def test_unknown_schema_rejected(deployment):
    source, _, importer = deployment
    with sqlite3.connect(source / "data/openbot.db") as database:
        database.execute("UPDATE schema_version SET version=12")
    with pytest.raises(ImportRejected, match="schema 11"):
        importer.preview(str(source))


def test_existing_target_data_rejected(deployment):
    source, settings, importer = deployment
    path = settings.data_dir / "data/personal_memory"
    path.mkdir(parents=True)
    (path / "existing.md").write_text("keep")
    with pytest.raises(ImportRejected, match="已有"):
        importer.preview(str(source))
    assert (path / "existing.md").read_text() == "keep"


def test_busy_source_is_rejected(deployment, monkeypatch):
    source, _, importer = deployment

    def busy(_):
        raise ImportRejected("源数据仍被进程打开")

    monkeypatch.setattr("src.desktop.import_plan.assert_stopped", busy)
    with pytest.raises(ImportRejected, match="进程"):
        importer.preview(str(source))


def test_publication_failure_restores_target(deployment, monkeypatch):
    source, settings, importer = deployment
    previous = settings.path.read_bytes()
    importer.stage(importer.preview(str(source))["preview_id"])
    rename = Path.rename
    failed = False

    def fail_once(path, target):
        nonlocal failed
        if (
            path.name == "desktop-state.json"
            and path.parent.name == "import-pending"
            and not failed
        ):
            failed = True
            raise OSError("synthetic interruption")
        return rename(path, target)

    monkeypatch.setattr(Path, "rename", fail_once)
    with pytest.raises(OSError):
        apply_pending_import(settings)
    assert settings.path.read_bytes() == previous
    assert not (settings.data_dir / "data/openbot.db").exists()
    assert not apply_pending_import(settings)


def test_credentials_only_read_selected_env_and_never_echoed(deployment, monkeypatch):
    source, settings, importer = deployment
    config = yaml.safe_load((source / "config.yaml").read_text())
    config["model"]["primary"].update(
        base_url="https://example.test/v1", api_key_env="SYNTHETIC_KEY"
    )
    config["telegram"]["webhook_secret"] = "synthetic-webhook-secret"
    (source / "config.yaml").write_text(yaml.safe_dump(config))
    (source / ".env").write_text(
        "SYNTHETIC_KEY=synthetic-local-key\nPATH=bad\nTAVILY_API_KEY=synthetic-search\n"
    )
    monkeypatch.setenv("SYNTHETIC_KEY", "must-not-import-host")
    preview = importer.preview(str(source))
    assert "synthetic-local-key" not in str(preview)
    importer.stage(preview["preview_id"])
    apply_pending_import(settings)
    state = settings.read()
    assert state.configured
    assert state.model.api_key == "synthetic-local-key"
    assert state.secrets["tavily.api_key"] == "synthetic-search"
    assert state.secrets["telegram.webhook_secret"] == "synthetic-webhook-secret"
    assert "PATH" not in state.secrets
    assert (source / ".env").read_text().startswith("SYNTHETIC_KEY=")
    assert "synthetic-webhook-secret" not in (settings.data_dir / "config.yaml").read_text()


def test_system_env_cannot_be_imported_as_business_key(deployment):
    source, settings, importer = deployment
    config = yaml.safe_load((source / "config.yaml").read_text())
    config["model"]["primary"].update(base_url="https://example.test/v1", api_key_env="HOME")
    (source / "config.yaml").write_text(yaml.safe_dump(config))
    (source / ".env").write_text("HOME=synthetic-do-not-import\n")
    importer.stage(importer.preview(str(source))["preview_id"])
    apply_pending_import(settings)
    assert not settings.read().configured
    assert not settings.read().model.api_key


def test_uncheckpointed_wal_rejected_without_reading_database(deployment):
    source, _, importer = deployment
    (source / "data/openbot.db-wal").write_bytes(b"synthetic-wal")
    with pytest.raises(ImportRejected, match="WAL"):
        importer.preview(str(source))


def test_copy_time_source_change_is_rejected_and_preserved(deployment, monkeypatch):
    source, settings, importer = deployment
    preview = importer.preview(str(source))
    original = importer._copy

    def changed(*args):
        original(*args)
        (source / "data/personal_memory/profile.md").write_text("changed-during-copy")

    monkeypatch.setattr(importer, "_copy", changed)
    with pytest.raises(ImportRejected, match="变化"):
        importer.stage(preview["preview_id"])
    assert not (settings.data_dir / "import-pending").exists()
    assert not (settings.data_dir / "data/openbot.db").exists()
    assert list(settings.data_dir.glob("import-rejected-*"))


def test_abandon_never_applies_on_later_restart(deployment):
    source, settings, importer = deployment
    importer.stage(importer.preview(str(source))["preview_id"])
    importer.abandon()
    assert not apply_pending_import(settings)
    assert not (settings.data_dir / "data/openbot.db").exists()


def test_restored_journal_is_idempotent(deployment):
    import json

    from src.desktop.import_publish import recover_import

    source, settings, importer = deployment
    original = settings.path.read_bytes()
    importer.stage(importer.preview(str(source))["preview_id"])
    backup = settings.data_dir / "import-backup-synthetic"
    backup.mkdir()
    settings.path.rename(backup / "desktop-state.json")
    (settings.data_dir / "import-pending/desktop-state.json").rename(settings.path)
    journal = settings.data_dir / "import-journal.json"
    payload = {
        "backup": backup.name,
        "started": ["desktop-state.json"],
        "existed": {"desktop-state.json": True},
    }
    journal.write_text(json.dumps(payload))
    recover_import(settings.data_dir, journal)
    assert settings.path.read_bytes() == original
    journal.write_text(json.dumps(payload))
    recover_import(settings.data_dir, journal)
    assert settings.path.read_bytes() == original


@pytest.mark.parametrize(
    "insertion",
    [
        "INSERT INTO memory_stage_results VALUES ('source','stage','{}',0)",
        "INSERT INTO personal_memory_progress VALUES ('source',1)",
        "INSERT INTO working_memory_summaries VALUES ('local','boundary','keep',1,'now')",
        "INSERT INTO personal_backfill_documents VALUES ('profile.md','revision')",
        "INSERT INTO memory_deliveries VALUES ('id','source','keep','[]','now',0)",
        "CREATE TABLE future_business (value TEXT); INSERT INTO future_business VALUES ('keep')",
    ],
)
def test_any_business_record_blocks_import_without_modifying_target(deployment, insertion):
    source, settings, importer = deployment
    data = settings.data_dir / "data"
    data.mkdir()
    path = data / "openbot.db"
    with sqlite3.connect(path) as database:
        database.executescript(SCHEMA_SQL.format(single_user_id="local"))
        database.executescript(insertion)
    previous = path.read_bytes()
    original_source = (source / "data/openbot.db").read_bytes()
    with pytest.raises(ImportRejected, match="已有业务数据"):
        importer.preview(str(source))
    assert path.read_bytes() == previous
    assert (source / "data/openbot.db").read_bytes() == original_source


async def test_real_initialized_vector_tables_are_empty_but_vector_records_are_protected(tmp_path):
    import sqlite_vec

    from src.core.config import StorageConfig
    from src.desktop.import_plan import ensure_empty
    from src.infrastructure.database import Database

    settings = DesktopSettings(tmp_path / "app")
    path = settings.data_dir / "data/openbot.db"
    database = Database(StorageConfig(db_path=str(path)), embedding_dimensions=3)
    await database.initialize()
    await database.close()
    with sqlite3.connect(path) as connection:
        connection.execute(
            "INSERT INTO logs(timestamp,level,event) VALUES ('now','INFO','startup')"
        )
        connection.execute(
            "INSERT INTO metrics(event_name,data,timestamp) VALUES ('startup','{}','now')"
        )
    ensure_empty(settings)
    with sqlite3.connect(path) as connection:
        connection.enable_load_extension(True)
        sqlite_vec.load(connection)
        connection.enable_load_extension(False)
        connection.execute(
            "INSERT INTO knowledge_embeddings(knowledge_id,embedding) VALUES (?,?)",
            ("synthetic", sqlite_vec.serialize_float32([1, 2, 3])),
        )
    previous = path.read_bytes()
    with pytest.raises(ImportRejected, match="已有业务数据"):
        ensure_empty(settings)
    assert path.read_bytes() == previous
    # Deleting a logical vector leaves backing allocation rows; these are index
    # structure rather than business data and must not block an otherwise empty DB.
    with sqlite3.connect(path) as connection:
        connection.enable_load_extension(True)
        sqlite_vec.load(connection)
        connection.enable_load_extension(False)
        connection.execute("DELETE FROM knowledge_embeddings")
    ensure_empty(settings)


@pytest.mark.parametrize(
    "crash_at", ["before_marker", "after_marker", "before_unlink", "after_unlink"]
)
def test_recovery_process_crash_cannot_leave_import_replayable(deployment, crash_at):
    import json
    import subprocess
    import sys

    source, settings, importer = deployment
    source_database = (source / "data/openbot.db").read_bytes()
    previous = settings.path.read_bytes()
    importer.stage(importer.preview(str(source))["preview_id"])
    backup = settings.data_dir / "import-backup-process-crash"
    backup.mkdir()
    settings.path.rename(backup / "desktop-state.json")
    (settings.data_dir / "import-pending/desktop-state.json").rename(settings.path)
    journal = settings.data_dir / "import-journal.json"
    journal.write_text(
        json.dumps(
            {
                "backup": backup.name,
                "started": ["desktop-state.json"],
                "existed": {"desktop-state.json": True},
            }
        )
    )
    script = """
import os, sys
from pathlib import Path
from src.desktop.import_publish import recover_import
root, crash_at = Path(sys.argv[1]), sys.argv[2]
rename, unlink = Path.rename, Path.unlink

def interrupted_rename(path, target):
    if path.name == "ready.json" and crash_at == "before_marker":
        os._exit(77)
    result = rename(path, target)
    if path.name == "ready.json" and crash_at == "after_marker":
        os._exit(77)
    return result

def interrupted_unlink(path, *args, **kwargs):
    if path.name == "import-journal.json" and crash_at == "before_unlink":
        os._exit(77)
    result = unlink(path, *args, **kwargs)
    if path.name == "import-journal.json" and crash_at == "after_unlink":
        os._exit(77)
    return result

Path.rename, Path.unlink = interrupted_rename, interrupted_unlink
recover_import(root, root / "import-journal.json")
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(settings.data_dir), crash_at],
        timeout=10,
        capture_output=True,
    )
    assert result.returncode == 77, result.stderr.decode()
    if journal.exists():
        with pytest.raises(RuntimeError, match="数据已恢复"):
            apply_pending_import(settings)
    assert settings.path.read_bytes() == previous
    assert not (settings.data_dir / "data/openbot.db").exists()
    assert not (settings.data_dir / "import-pending/ready.json").exists()
    assert not apply_pending_import(settings)
    assert (source / "data/openbot.db").read_bytes() == source_database
    assert (source / "data/personal_memory/profile.md").read_text() == "合成档案"
    assert (backup / "failed-manifest.json").exists()


def test_nonstandard_wechat_state_path_is_rejected_without_losing_login(deployment):
    source, settings, importer = deployment
    config = yaml.safe_load((source / "config.yaml").read_text())
    config["wechat"]["state_path"] = "data/custom_wechat.json"
    (source / "config.yaml").write_text(yaml.safe_dump(config))
    custom = source / "data/custom_wechat.json"
    custom.write_text('{"synthetic_private_login":"preserve"}')
    with pytest.raises(ImportRejected, match="微信状态路径"):
        importer.preview(str(source))
    assert custom.read_text() == '{"synthetic_private_login":"preserve"}'
    assert not (settings.data_dir / "import-pending").exists()


def test_nested_database_names_are_copied_as_ordinary_data(deployment):
    source, settings, importer = deployment
    examples = [
        "data/skills/example/references/openbot.db",
        "data/file_snapshots/example/openbot.db-wal",
        "data/skills/example/openbot.db-shm",
    ]
    for name in examples:
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"synthetic-reference-not-a-sqlite-database")
    importer.stage(importer.preview(str(source))["preview_id"])
    assert apply_pending_import(settings)
    for name in examples:
        assert (settings.data_dir / name).read_bytes() == (source / name).read_bytes()


@pytest.mark.parametrize("name", ["foo.txt", "unknown/nested/keep.txt", "logs/custom.log"])
@pytest.mark.parametrize("content", [b"", b"synthetic-user-data"])
def test_unknown_destination_files_are_never_treated_as_initialization(deployment, name, content):
    source, settings, importer = deployment
    path = settings.data_dir / "data" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    with pytest.raises(ImportRejected, match="已有本地数据"):
        importer.preview(str(source))
    assert path.read_bytes() == content
    assert not (settings.data_dir / "import-pending").exists()


def test_empty_destination_directories_and_fixed_startup_logs_are_allowed(deployment):
    source, settings, importer = deployment
    for name in ("empty/nested", "personal_memory", "logs"):
        (settings.data_dir / "data" / name).mkdir(parents=True)
    (settings.data_dir / "data/logs/openbot.log").write_text("synthetic startup log")
    assert importer.preview(str(source))["preview_id"]


@pytest.mark.parametrize(
    "name", ["linked", "logs/openbot.log", "openbot.db", "unknown/nested-link"]
)
def test_destination_links_are_rejected_even_when_the_target_is_empty(deployment, tmp_path, name):
    source, settings, importer = deployment
    outside = tmp_path / "empty-outside"
    outside.mkdir()
    path = settings.data_dir / "data" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ImportRejected, match="链接或特殊项"):
        importer.preview(str(source))
    assert path.is_symlink()
    assert not list(outside.iterdir())


def test_destination_data_directory_symlink_and_fifo_are_rejected(deployment, tmp_path):
    import os

    source, settings, importer = deployment
    outside = tmp_path / "empty-outside"
    outside.mkdir()
    data = settings.data_dir / "data"
    data.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ImportRejected, match="链接或特殊项"):
        importer.preview(str(source))
    data.rename(settings.data_dir / "preserved-link")
    data.mkdir()
    os.mkfifo(data / "named-pipe")
    with pytest.raises(ImportRejected, match="链接或特殊项"):
        importer.preview(str(source))
    assert not list(outside.iterdir())
