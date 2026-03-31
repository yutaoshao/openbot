from __future__ import annotations

from pathlib import Path

from src.core.config import StorageConfig


def test_storage_config_expands_user_in_workspace_path() -> None:
    config = StorageConfig(workspace_path="~/Project/openbot")

    assert config.workspace_path == str(Path("~/Project/openbot").expanduser())
