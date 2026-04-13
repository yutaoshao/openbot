from __future__ import annotations

import base64
import hashlib
import json

import pytest
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from src.channels.adapters.feishu_security import (
    FeishuWebhookError,
    build_signature,
    decode_callback_body,
    verify_callback_signature,
)

_TEST_ENCRYPT_KEY = "encrypt_test"
_TEST_IV = bytes(range(16))


def _encrypt_payload(body: dict[str, object], encrypt_key: str = _TEST_ENCRYPT_KEY) -> bytes:
    plaintext = json.dumps(body).encode("utf-8")
    padding = 16 - (len(plaintext) % 16)
    padded = plaintext + bytes([padding]) * padding
    digest = hashlib.sha256(encrypt_key.encode("utf-8")).digest()
    cipher = Cipher(algorithms.AES(digest), modes.CBC(_TEST_IV))
    encryptor = cipher.encryptor()
    encrypted = _TEST_IV + encryptor.update(padded) + encryptor.finalize()
    payload = {"encrypt": base64.b64encode(encrypted).decode("utf-8")}
    return json.dumps(payload).encode("utf-8")


def test_decode_callback_body_decrypts_encrypted_payload() -> None:
    payload = _encrypt_payload({
        "header": {"token": "verify_test", "event_type": "im.message.receive_v1"},
        "event": {"message": {"message_type": "text", "content": "{\"text\":\"hello\"}"}},
    })

    body, encrypted = decode_callback_body(payload, _TEST_ENCRYPT_KEY)

    assert encrypted is True
    assert body["header"]["token"] == "verify_test"


def test_decode_callback_body_rejects_missing_encrypt_key() -> None:
    payload = _encrypt_payload({"token": "verify_test", "challenge": "abc"})

    with pytest.raises(FeishuWebhookError):
        decode_callback_body(payload, "")


def test_verify_callback_signature_rejects_bad_signature() -> None:
    payload = _encrypt_payload({"token": "verify_test"})

    with pytest.raises(FeishuWebhookError):
        verify_callback_signature(payload, {
            "x-lark-request-timestamp": "123",
            "x-lark-request-nonce": "456",
            "x-lark-signature": "bad-signature",
        }, _TEST_ENCRYPT_KEY)


def test_build_signature_matches_verifier_input() -> None:
    payload = _encrypt_payload({"token": "verify_test"})
    signature = build_signature(payload, "123", "456", _TEST_ENCRYPT_KEY)

    verify_callback_signature(payload, {
        "x-lark-request-timestamp": "123",
        "x-lark-request-nonce": "456",
        "x-lark-signature": signature,
    }, _TEST_ENCRYPT_KEY)
