from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from src.core.config import AppConfig
from src.desktop.launcher import _load_config
from src.desktop.settings import (
    MODEL_KEY_ENV,
    DesktopSettings,
    DesktopSettingsService,
)


def test_fresh_install_is_private_and_does_not_enable_execution(tmp_path: Path) -> None:
    settings = DesktopSettings(tmp_path / "application")
    state = settings.read()
    assert not state.configured
    assert state.permissions == {"bash": False, "code_executor": False}
    assert Path(state.work_dir).is_dir()
    assert stat.S_IMODE(settings.path.stat().st_mode) == 0o600
    assert stat.S_IMODE(settings.data_dir.stat().st_mode) == 0o700


def test_workspace_change_preserves_application_data_and_original_workspace(tmp_path: Path) -> None:
    settings = DesktopSettings(tmp_path / "application")
    data = settings.data_dir / "data" / "conversations"
    data.mkdir(parents=True)
    history = data / "history.jsonl"
    history.write_text("synthetic existing history\n")
    old_workspace = Path(settings.read().work_dir)
    (old_workspace / "note.txt").write_text("old workspace")
    workspace = tmp_path / "new-workspace"
    workspace.mkdir()
    state = settings.prepare_setup(
        {
            "provider": "openai_compatible",
            "base_url": "http://127.0.0.1:12345/v1",
            "model": "local",
        },
        str(workspace),
    )
    settings.save(state)
    assert history.read_text() == "synthetic existing history\n"
    assert (old_workspace / "note.txt").read_text() == "old workspace"
    assert settings.read().work_dir == str(workspace)
    assert settings.read().configured


def test_remote_model_requires_credential_and_blank_update_preserves_key(tmp_path: Path) -> None:
    settings = DesktopSettings(tmp_path / "application")
    model = {
        "provider": "openai_responses",
        "base_url": "https://example.invalid/v1",
        "model": "test",
    }
    with pytest.raises(ValueError, match="API Key"):
        settings.prepare_setup(model, settings.read().work_dir)
    state = settings.prepare_setup(
        {**model, "api_key": "synthetic-secret"}, settings.read().work_dir
    )
    settings.save(state)
    updated = settings.prepare_setup({**model, "api_key": ""}, state.work_dir)
    assert updated.model.api_key == "synthetic-secret"


def test_desktop_config_and_secrets_do_not_search_parent_environment(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PYTHON_DOTENV_DISABLED", "1")
    monkeypatch.setenv(MODEL_KEY_ENV, "synthetic-before-install")
    monkeypatch.delenv("OPENBOT_PARENT_SENTINEL", raising=False)
    (tmp_path / ".env").write_text("OPENBOT_PARENT_SENTINEL=must-not-load\n")
    root = tmp_path / "application"
    settings = DesktopSettings(root)
    config = _load_config(root / "config.yaml")
    prepared = settings.prepare_config(config, 43210, tmp_path / "runtime")
    settings.install_model_key()
    assert "OPENBOT_PARENT_SENTINEL" not in os.environ
    assert prepared.api.host == "127.0.0.1" and prepared.api.port == 43210
    assert prepared.storage.db_path == str(root / "data" / "openbot.db")
    assert not prepared.telegram.enabled
    assert prepared.model.primary.api_key_env == MODEL_KEY_ENV
    values = DesktopSettingsService(str(root / "config.yaml"), settings).read_secret_values(
        prepared
    )
    primary = next(item for item in values if item.env_name == MODEL_KEY_ENV)
    assert primary.value == "" and not primary.is_set


def test_runtime_overrides_cannot_move_database_or_expose_management(tmp_path: Path) -> None:
    settings = DesktopSettings(tmp_path / "application")
    config = AppConfig(
        api={"host": "0.0.0.0", "local_only": False}, storage={"db_path": "/wrong.db"}
    )
    prepared = settings.prepare_config(config, 43210, tmp_path / "runtime")
    assert prepared.api.local_only and prepared.api.host == "127.0.0.1"
    assert Path(prepared.storage.db_path).is_relative_to(settings.data_dir)
