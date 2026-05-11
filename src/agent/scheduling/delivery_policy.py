"""Delivery constraints for scheduled task results."""

from __future__ import annotations

WECHAT_PLATFORM = "wechat"
TELEGRAM_PLATFORM = "telegram"

WECHAT_PROACTIVE_SEND_UNSUPPORTED = (
    "微信当前只能在你发来消息后回复，不能主动推送定时任务结果。"
)
TELEGRAM_TARGET_ID_INVALID = (
    "Telegram target_id must be the numeric chat id, not the platform name. "
    "Omit target_id to use the current Telegram conversation, or pass the real chat id."
)
WECHAT_SCHEDULE_CREATE_UNSUPPORTED = (
    f"{WECHAT_PROACTIVE_SEND_UNSUPPORTED}\n\n"
    "这个定时任务还没有创建。请在 Telegram 里发送同样的请求，"
    "或指定 Telegram 作为通知目标。"
)
WECHAT_SCHEDULE_UPDATE_UNSUPPORTED = (
    f"{WECHAT_PROACTIVE_SEND_UNSUPPORTED}\n\n"
    "这个定时任务没有更新。请改用 Telegram 作为通知目标。"
)


def is_wechat_delivery_target(target_platform: str | None) -> bool:
    """Return whether a schedule target points at WeChat delivery."""
    return (target_platform or "").strip().lower() == WECHAT_PLATFORM


def is_telegram_delivery_target(target_platform: str | None) -> bool:
    """Return whether a schedule target points at Telegram delivery."""
    return (target_platform or "").strip().lower() == TELEGRAM_PLATFORM


def assert_supported_schedule_target(
    target_platform: str | None,
    *,
    target_id: str | None = None,
) -> None:
    """Raise when a scheduled task target cannot receive proactive sends."""
    if is_wechat_delivery_target(target_platform):
        raise ValueError(WECHAT_PROACTIVE_SEND_UNSUPPORTED)
    if is_telegram_delivery_target(target_platform) and not _is_int_string(target_id):
        raise ValueError(TELEGRAM_TARGET_ID_INVALID)


def _is_int_string(value: str | None) -> bool:
    if not value:
        return True
    try:
        int(value.strip())
    except ValueError:
        return False
    return True
