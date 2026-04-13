"""Webhook routes for platform integrations (Telegram, Feishu).

These endpoints receive push notifications from external platforms
and feed them into the corresponding adapter for processing.
"""

from __future__ import annotations

import hmac

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from src.channels.adapters.feishu_security import FeishuWebhookError
from src.core.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/webhook", tags=["webhook"])


# ---------------------------------------------------------------------------
# Telegram webhook
# ---------------------------------------------------------------------------

@router.post("/telegram")
async def telegram_webhook(request: Request) -> JSONResponse:
    """Receive Telegram Bot API updates via webhook.

    Telegram sends a JSON-serialized ``Update`` object.
    When a ``webhook_secret`` is configured, validates the
    ``X-Telegram-Bot-Api-Secret-Token`` header before processing.
    """
    telegram = getattr(request.app.state, "telegram", None)
    if telegram is None:
        return JSONResponse(
            status_code=503,
            content={"ok": False, "error": "Telegram adapter not available"},
        )

    # Verify secret token if configured
    config = getattr(request.app.state, "config", None)
    if config and config.telegram.webhook_secret:
        secret_header = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if not hmac.compare_digest(secret_header, config.telegram.webhook_secret):
            logger.warning("webhook.telegram_secret_mismatch")
            return JSONResponse(
                status_code=403,
                content={"ok": False, "error": "Invalid secret token"},
            )

    try:
        from telegram import Update

        data = await request.json()
        update = Update.de_json(data, telegram.app.bot)
        if update:
            await telegram.app.process_update(update)
        return JSONResponse(content={"ok": True})
    except Exception:
        logger.exception("webhook.telegram_error")
        return JSONResponse(
            status_code=500,
            content={"ok": False, "error": "Internal error"},
        )


# ---------------------------------------------------------------------------
# Feishu webhook
# ---------------------------------------------------------------------------

@router.post("/feishu")
async def feishu_webhook(request: Request) -> JSONResponse:
    """Receive Feishu event callbacks.

    Handles:
    - URL verification challenge (returns challenge token)
    - im.message.receive_v1 events (incoming messages)
    """
    feishu = getattr(request.app.state, "feishu", None)
    if feishu is None:
        return JSONResponse(
            status_code=503,
            content={"ok": False, "error": "Feishu adapter not available"},
        )

    try:
        payload = await request.body()
        result = await feishu.process_callback(payload, request.headers)
        return JSONResponse(content=result)
    except FeishuWebhookError as exc:
        logger.warning(
            "webhook.feishu_validation_failed",
            status_code=exc.status_code,
            error=str(exc),
        )
        return JSONResponse(
            status_code=exc.status_code,
            content={"ok": False, "error": str(exc)},
        )
    except Exception:
        logger.exception("webhook.feishu_error")
        return JSONResponse(
            status_code=500,
            content={"ok": False, "error": "Internal error"},
        )
