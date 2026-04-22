from __future__ import annotations

from pathlib import Path

from src.core.config import FeishuConfig, StorageConfig, TelegramConfig, WeChatConfig


def test_storage_config_expands_user_in_workspace_path() -> None:
    config = StorageConfig(workspace_path="~/Project/openbot")

    assert config.workspace_path == str(Path("~/Project/openbot").expanduser())


def test_wechat_config_expands_user_in_state_path() -> None:
    config = WeChatConfig(state_path="~/data/wechat/ilink_state.json")

    assert config.state_path == str(Path("~/data/wechat/ilink_state.json").expanduser())


def test_feishu_long_connection_requires_only_app_credentials(monkeypatch) -> None:
    monkeypatch.setenv("FEISHU_APP_ID", "cli_test")
    monkeypatch.setenv("FEISHU_APP_SECRET", "secret_test")
    monkeypatch.delenv("FEISHU_VERIFICATION_TOKEN", raising=False)
    monkeypatch.delenv("FEISHU_ENCRYPT_KEY", raising=False)

    config = FeishuConfig(enabled=True, mode="long_connection")

    assert config.missing_required_env_vars() == []


def test_feishu_webhook_requires_token_and_encrypt_key(monkeypatch) -> None:
    monkeypatch.setenv("FEISHU_APP_ID", "cli_test")
    monkeypatch.setenv("FEISHU_APP_SECRET", "secret_test")
    monkeypatch.delenv("FEISHU_VERIFICATION_TOKEN", raising=False)
    monkeypatch.delenv("FEISHU_ENCRYPT_KEY", raising=False)

    config = FeishuConfig(enabled=True, mode="webhook")

    assert config.missing_required_env_vars() == [
        "FEISHU_VERIFICATION_TOKEN",
        "FEISHU_ENCRYPT_KEY",
    ]


def test_telegram_disabled_requires_no_token(monkeypatch) -> None:
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)

    config = TelegramConfig(enabled=False)

    assert config.missing_required_env_vars() == []


def test_telegram_enabled_requires_token(monkeypatch) -> None:
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)

    config = TelegramConfig(enabled=True)

    assert config.missing_required_env_vars() == ["TELEGRAM_BOT_TOKEN"]
