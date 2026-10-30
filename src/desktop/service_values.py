"""Numerical and strict state constraints at the desktop configuration boundary."""

from __future__ import annotations

import math


def _number(
    values: dict,
    key: str,
    *,
    minimum: float,
    maximum: float = math.inf,
    integer: bool = False,
    optional: bool = False,
    exclusive: bool = False,
) -> None:
    if key not in values or (optional and values[key] is None):
        return
    value = values[key]
    valid_type = type(value) is int if integer else type(value) in {int, float}
    if not valid_type or not math.isfinite(value):
        raise ValueError("数值类型无效。")
    if value < minimum or value > maximum or (exclusive and value == minimum):
        raise ValueError("数值超出支持范围。")


def _boolean(values: dict, key: str) -> None:
    if key in values and type(values[key]) is not bool:
        raise ValueError("开关必须是布尔值。")


def _model_values(model: dict) -> None:
    _number(model, "max_tokens", minimum=1, integer=True)
    _number(model, "context_window", minimum=1, integer=True, optional=True)
    if model.get("context_window") is not None and model["context_window"] <= model.get(
        "max_tokens", 4096
    ):
        raise ValueError("上下文窗口必须大于输出预留。")
    _number(model, "temperature", minimum=0, maximum=2)
    for key in ("pricing_input", "pricing_output"):
        _number(model, key, minimum=0, optional=True)
    for key in ("connect_timeout", "read_timeout"):
        _number(model, key, minimum=0, exclusive=True)


def validate_service_values(configuration: dict) -> None:
    """Check user-provided numbers before Pydantic can coerce booleans or strings."""
    model = configuration["model"]
    for entry in [model["primary"], model.get("fallback"), *model["routing"]["tiers"].values()]:
        if entry is not None:
            _model_values(entry)
    _number(model, "max_retries", minimum=0, maximum=10, integer=True)
    _number(model, "retry_base_delay", minimum=0, exclusive=True)
    routing = model["routing"]
    _boolean(routing, "enabled")
    rules = routing.get("rules", {})
    if not isinstance(rules, dict):
        raise ValueError("路由规则格式无效。")
    for key in ("simple_max_chars", "complex_min_chars", "tool_count_complex_threshold"):
        _number(rules, key, minimum=1, integer=True)
    if rules.get("simple_max_chars", 120) >= rules.get("complex_min_chars", 600):
        raise ValueError("复杂请求长度阈值必须大于简单请求阈值。")
    for name in ("telegram", "feishu", "wechat", "embedding", "reranker"):
        _boolean(configuration[name], "enabled")
    telegram = configuration["telegram"]
    _boolean(telegram, "enable_streaming")
    _number(telegram, "stream_throttle", minimum=0, exclusive=True)
    identifiers = telegram.get("allowed_user_ids", [])
    if not isinstance(identifiers, list) or any(
        type(value) is not int or value <= 0 for value in identifiers
    ):
        raise ValueError("Telegram用户ID必须为正整数。")
    _number(configuration["embedding"], "dimensions", minimum=1, integer=True)
    _number(configuration["reranker"], "top_n", minimum=1, integer=True)
    wechat = configuration["wechat"]
    for key in ("poll_interval", "max_backoff"):
        _number(wechat, key, minimum=0, exclusive=True)
    if wechat.get("max_backoff", 30) < wechat.get("poll_interval", 2):
        raise ValueError("微信重试上限不能小于轮询间隔。")
