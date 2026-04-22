from __future__ import annotations

import base64
import hashlib
import json
from typing import Any

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from fastapi.testclient import TestClient

from src.api.app import create_api_app
from src.channels.adapters.feishu import FeishuAdapter
from src.channels.adapters.feishu_security import build_signature
from src.core.config import AppConfig, FeishuConfig

_TEST_ENCRYPT_KEY = "encrypt_test"
_TEST_IV = bytes(range(16))


class _RecordingMsgHub:
    def __init__(self) -> None:
        self.messages: list[Any] = []

    async def handle_incoming(self, message: Any) -> None:
        self.messages.append(message)


def _set_feishu_env(monkeypatch: Any) -> None:
    monkeypatch.setenv("FEISHU_APP_ID", "cli_test")
    monkeypatch.setenv("FEISHU_APP_SECRET", "secret_test")
    monkeypatch.setenv("FEISHU_VERIFICATION_TOKEN", "verify_test")
    monkeypatch.setenv("FEISHU_ENCRYPT_KEY", _TEST_ENCRYPT_KEY)


def _encrypt_payload(body: dict[str, object]) -> bytes:
    plaintext = json.dumps(body).encode("utf-8")
    padding = 16 - (len(plaintext) % 16)
    padded = plaintext + bytes([padding]) * padding
    digest = hashlib.sha256(_TEST_ENCRYPT_KEY.encode("utf-8")).digest()
    cipher = Cipher(algorithms.AES(digest), modes.CBC(_TEST_IV))
    encryptor = cipher.encryptor()
    encrypted = _TEST_IV + encryptor.update(padded) + encryptor.finalize()
    payload = {"encrypt": base64.b64encode(encrypted).decode("utf-8")}
    return json.dumps(payload).encode("utf-8")


def _client(monkeypatch: Any) -> tuple[TestClient, _RecordingMsgHub]:
    _set_feishu_env(monkeypatch)
    config = AppConfig(feishu=FeishuConfig(enabled=True))
    msg_hub = _RecordingMsgHub()
    adapter = FeishuAdapter(config.feishu, msg_hub)  # type: ignore[arg-type]
    app = create_api_app(config=config)
    app.state.feishu = adapter
    return TestClient(app, client=("127.0.0.1", 50000)), msg_hub


def test_feishu_webhook_returns_challenge(monkeypatch: Any) -> None:
    client, _ = _client(monkeypatch)

    response = client.post(
        "/webhook/feishu",
        json={
            "challenge": "challenge_test",
            "token": "verify_test",
        },
    )

    assert response.status_code == 200
    assert response.json() == {"challenge": "challenge_test"}


def test_feishu_webhook_rejects_invalid_token(monkeypatch: Any) -> None:
    client, _ = _client(monkeypatch)

    response = client.post(
        "/webhook/feishu",
        json={
            "challenge": "challenge_test",
            "token": "wrong_token",
        },
    )

    assert response.status_code == 403
    assert response.json()["error"] == "Invalid Feishu verification token."


def test_feishu_webhook_rejects_invalid_signature(monkeypatch: Any) -> None:
    client, _ = _client(monkeypatch)
    payload = _encrypt_payload(
        {
            "header": {
                "event_type": "im.message.receive_v1",
                "token": "verify_test",
            },
            "event": {
                "sender": {"sender_id": {"open_id": "ou_test"}},
                "message": {
                    "message_id": "om_123",
                    "chat_id": "oc_456",
                    "message_type": "text",
                    "content": json.dumps({"text": "hello"}),
                },
            },
        }
    )

    response = client.post(
        "/webhook/feishu",
        content=payload,
        headers={
            "content-type": "application/json",
            "x-lark-request-timestamp": "123",
            "x-lark-request-nonce": "456",
            "x-lark-signature": "bad-signature",
        },
    )

    assert response.status_code == 403
    assert response.json()["error"] == "Invalid Feishu signature."


def test_feishu_webhook_publishes_text_message(monkeypatch: Any) -> None:
    client, msg_hub = _client(monkeypatch)
    payload = _encrypt_payload(
        {
            "header": {
                "event_type": "im.message.receive_v1",
                "token": "verify_test",
            },
            "event": {
                "sender": {"sender_id": {"open_id": "ou_test"}},
                "message": {
                    "message_id": "om_123",
                    "chat_id": "oc_456",
                    "message_type": "text",
                    "content": json.dumps({"text": "@_user_1 hello"}),
                },
            },
        }
    )
    headers = {
        "content-type": "application/json",
        "x-lark-request-timestamp": "123",
        "x-lark-request-nonce": "456",
        "x-lark-signature": build_signature(payload, "123", "456", _TEST_ENCRYPT_KEY),
    }

    response = client.post("/webhook/feishu", content=payload, headers=headers)

    assert response.status_code == 200
    assert response.json() == {"code": 0, "msg": "ok"}
    assert len(msg_hub.messages) == 1
    message = msg_hub.messages[0]
    assert message.platform == "feishu"
    assert message.sender_id == "ou_test"
    assert message.conversation_id == "oc_456"
    assert message.content.text == "hello"
