from __future__ import annotations

from src.core.logging import _sanitize_pii


def test_sanitize_pii_uses_specific_placeholder_types() -> None:
    event = {
        "email": "alice@example.com",
        "phone": "+86 138 0013 8000",
        "bearer": "Bearer abcdefghijklmnopqrstuvwxyz123456",
        "secret_key": "sk-abcdefghijklmnopqrstuvwxyz123456",
        "access_token": "tok_abcdefghijklmnopqrstuvwxyz123456",
        "api_key": "key_abcdefghijklmnopqrstuvwxyz123456",
    }

    sanitized = _sanitize_pii(None, "info", event)

    assert sanitized["email"] == "[REDACTED_EMAIL]"
    assert sanitized["phone"] == "[REDACTED_PHONE]"
    assert sanitized["bearer"] == "[REDACTED_BEARER_TOKEN]"
    assert sanitized["secret_key"] == "[REDACTED_SECRET_KEY]"
    assert sanitized["access_token"] == "[REDACTED_ACCESS_TOKEN]"
    assert sanitized["api_key"] == "[REDACTED_API_KEY]"


def test_sanitize_pii_keeps_context_while_redacting_multiple_types() -> None:
    event = {
        "message": (
            "contact alice@example.com or +86 138 0013 8000 with "
            "Bearer abcdefghijklmnopqrstuvwxyz123456"
        ),
    }

    sanitized = _sanitize_pii(None, "info", event)

    assert "[REDACTED_EMAIL]" in sanitized["message"]
    assert "[REDACTED_PHONE]" in sanitized["message"]
    assert "[REDACTED_BEARER_TOKEN]" in sanitized["message"]
