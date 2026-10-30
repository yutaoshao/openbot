from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock

import pytest

from src.desktop.settings import DesktopSettings
from src.desktop.wechat_login import DesktopWeChatLogin, _allowed_endpoint


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://ilinkai.weixin.qq.com",
        "https://weixin.qq.com.evil.invalid",
        "https://user:secret@ilinkai.weixin.qq.com",
        "https://ilinkai.weixin.qq.com:8443",
        "https://127.0.0.1",
    ],
)
def test_login_disallows_untrusted_token_redirects(endpoint):
    with pytest.raises(ValueError):
        _allowed_endpoint(endpoint)


async def test_login_confirmation_writes_private_state_without_exposing_token(
    tmp_path, monkeypatch
):
    client = AsyncMock()
    client.fetch_login_qrcode.return_value = {
        "qrcode": "synthetic-code",
        "qrcode_img_content": "https://weixin.qq.com/synthetic",
    }
    client.poll_login_status.return_value = {
        "status": "confirmed",
        "ilink_bot_id": "synthetic-account",
        "bot_token": "synthetic-private-token",
    }
    monkeypatch.setattr("src.desktop.wechat_login.WeChatIlinkClient", lambda _: client)
    settings = DesktopSettings(tmp_path / "app")
    login = DesktopWeChatLogin(settings)
    initial = await login.start("https://ilinkai.weixin.qq.com")
    assert initial["qr_image"].startswith("data:image/png;base64,")
    await login._task
    snapshot = login.snapshot(initial["session_id"])
    assert snapshot["status"] == "confirmed"
    assert "synthetic-private-token" not in str(snapshot)
    path = settings.data_dir / "data/wechat/ilink_state.json"
    assert json.loads(path.read_text())["bot_token"] == "synthetic-private-token"
    assert path.stat().st_mode & 0o777 == 0o600
    client.stop.assert_awaited_once()


async def test_login_cancel_closes_pending_poll_and_does_not_save(tmp_path, monkeypatch):
    client = AsyncMock()
    client.fetch_login_qrcode.return_value = {
        "qrcode": "synthetic",
        "qrcode_img_content": "synthetic",
    }
    started = asyncio.Event()

    async def wait(**kwargs):
        started.set()
        await asyncio.Event().wait()

    client.poll_login_status.side_effect = wait
    monkeypatch.setattr("src.desktop.wechat_login.WeChatIlinkClient", lambda _: client)
    settings = DesktopSettings(tmp_path / "app")
    login = DesktopWeChatLogin(settings)
    session = await login.start("https://ilinkai.weixin.qq.com")
    await started.wait()
    await login.cancel()
    assert login.snapshot(session["session_id"])["status"] == "cancelled"
    assert not (settings.data_dir / "data/wechat/ilink_state.json").exists()
    client.stop.assert_awaited_once()


async def test_expiry_and_redirect_failure_do_not_replace_saved_account(tmp_path, monkeypatch):
    from src.desktop.settings import write_private_json

    settings = DesktopSettings(tmp_path / "app")
    path = settings.data_dir / "data/wechat/ilink_state.json"
    write_private_json(path, {"synthetic_previous": True})
    previous = path.read_bytes()
    client = AsyncMock()
    client.fetch_login_qrcode.return_value = {
        "qrcode": "synthetic",
        "qrcode_img_content": "synthetic",
    }
    client.poll_login_status.return_value = {
        "status": "scaned_but_redirect",
        "redirect_host": "https://untrusted.invalid",
    }
    monkeypatch.setattr("src.desktop.wechat_login.WeChatIlinkClient", lambda _: client)
    login = DesktopWeChatLogin(settings)
    session = await login.start("https://ilinkai.weixin.qq.com")
    await login._task
    assert login.snapshot(session["session_id"])["status"] == "failed"
    assert path.read_bytes() == previous
    client.poll_login_status.return_value = {"status": "expired"}
    session = await login.start("https://ilinkai.weixin.qq.com")
    await login._task
    assert login.snapshot(session["session_id"])["status"] == "expired"
    assert path.read_bytes() == previous
    assert not await login.cancel("old-session-id")
