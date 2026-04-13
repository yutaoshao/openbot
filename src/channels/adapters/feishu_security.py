"""Feishu callback security helpers."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from collections.abc import Mapping
from typing import Any

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

_AES_BLOCK_SIZE = 16
_UTF8 = "utf-8"
_LARK_REQUEST_SIGNATURE = "x-lark-signature"
_LARK_REQUEST_TIMESTAMP = "x-lark-request-timestamp"
_LARK_REQUEST_NONCE = "x-lark-request-nonce"


class FeishuWebhookError(ValueError):
    """Raised when a Feishu callback is invalid."""

    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


def decode_callback_body(
    payload: bytes,
    encrypt_key: str,
) -> tuple[dict[str, Any], bool]:
    """Decode a Feishu callback payload, decrypting when needed."""
    body = _load_json(payload.decode(_UTF8))
    encrypted = body.get("encrypt")
    if not isinstance(encrypted, str) or not encrypted:
        return body, False
    if not encrypt_key:
        raise FeishuWebhookError(
            "Encrypted callback received but FEISHU_ENCRYPT_KEY is not configured.",
            status_code=503,
        )
    plaintext = _decrypt(encrypted, encrypt_key)
    return _load_json(plaintext), True


def extract_verification_token(body: Mapping[str, Any]) -> str:
    """Extract the verification token from either v1 or v2 payload shape."""
    header = body.get("header")
    if isinstance(header, Mapping):
        token = header.get("token")
        if isinstance(token, str):
            return token
    token = body.get("token")
    return token if isinstance(token, str) else ""


def build_signature(
    payload: bytes,
    timestamp: str,
    nonce: str,
    encrypt_key: str,
) -> str:
    """Build the Feishu callback SHA-256 signature."""
    message = (timestamp + nonce + encrypt_key).encode(_UTF8) + payload
    return hashlib.sha256(message).hexdigest()


def verify_callback_signature(
    payload: bytes,
    headers: Mapping[str, str],
    encrypt_key: str,
) -> None:
    """Verify Feishu callback signature when encrypted callbacks are enabled."""
    if not encrypt_key:
        return
    timestamp = _get_header(headers, _LARK_REQUEST_TIMESTAMP)
    nonce = _get_header(headers, _LARK_REQUEST_NONCE)
    signature = _get_header(headers, _LARK_REQUEST_SIGNATURE)
    if not timestamp or not nonce or not signature:
        raise FeishuWebhookError(
            "Missing Feishu signature headers.",
            status_code=403,
        )
    expected = build_signature(payload, timestamp, nonce, encrypt_key)
    if not hmac.compare_digest(signature, expected):
        raise FeishuWebhookError(
            "Invalid Feishu signature.",
            status_code=403,
        )


def _decrypt(encrypted: str, encrypt_key: str) -> str:
    decoded = base64.b64decode(encrypted)
    iv = decoded[:_AES_BLOCK_SIZE]
    ciphertext = decoded[_AES_BLOCK_SIZE:]
    digest = hashlib.sha256(encrypt_key.encode(_UTF8)).digest()
    cipher = Cipher(algorithms.AES(digest), modes.CBC(iv))
    decryptor = cipher.decryptor()
    padded = decryptor.update(ciphertext) + decryptor.finalize()
    return _remove_padding(padded).decode(_UTF8)


def _remove_padding(padded: bytes) -> bytes:
    if not padded:
        raise FeishuWebhookError("Encrypted callback payload is empty.")
    padding = padded[-1]
    if padding < 1 or padding > _AES_BLOCK_SIZE:
        raise FeishuWebhookError("Encrypted callback payload has invalid padding.")
    if padded[-padding:] != bytes([padding]) * padding:
        raise FeishuWebhookError("Encrypted callback payload has inconsistent padding.")
    return padded[:-padding]


def _load_json(raw: str) -> dict[str, Any]:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise FeishuWebhookError("Invalid Feishu callback JSON.") from exc
    if not isinstance(data, dict):
        raise FeishuWebhookError("Feishu callback payload must be a JSON object.")
    return data


def _get_header(headers: Mapping[str, str], name: str) -> str:
    for key, value in headers.items():
        if key.lower() == name:
            return value
    return ""
