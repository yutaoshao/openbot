"""Delivery constraints for scheduled task results."""

from __future__ import annotations

WECHAT_PLATFORM = "wechat"

WECHAT_PROACTIVE_SEND_UNSUPPORTED = (
    "微信当前只能在你发来消息后回复，不能主动推送定时任务结果。"
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


def assert_supported_schedule_target(target_platform: str | None) -> None:
    """Raise when a scheduled task target cannot receive proactive sends."""
    if is_wechat_delivery_target(target_platform):
        raise ValueError(WECHAT_PROACTIVE_SEND_UNSUPPORTED)
