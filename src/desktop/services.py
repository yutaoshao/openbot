"""Desktop-owned service configuration and credentials, published as one private file."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from src.core.config import AppConfig
from src.desktop.service_values import validate_service_values
from src.desktop.settings import (
    MODEL_KEY_ENV,
    DesktopModel,
    DesktopSettings,
    DesktopState,
    is_local_endpoint,
)

SECTIONS = ("model", "telegram", "feishu", "wechat", "embedding", "reranker")
SECRET_ENVS = {
    "model.primary": MODEL_KEY_ENV,
    "model.fallback": "OPENBOT_DESKTOP_FALLBACK_KEY",
    "model.routing.simple": "OPENBOT_DESKTOP_SIMPLE_KEY",
    "model.routing.complex": "OPENBOT_DESKTOP_COMPLEX_KEY",
    "telegram.bot_token": "OPENBOT_DESKTOP_TELEGRAM_TOKEN",
    "telegram.webhook_secret": "OPENBOT_DESKTOP_TELEGRAM_WEBHOOK_SECRET",
    "feishu.app_id": "OPENBOT_DESKTOP_FEISHU_APP_ID",
    "feishu.app_secret": "OPENBOT_DESKTOP_FEISHU_APP_SECRET",
    "feishu.verification_token": "OPENBOT_DESKTOP_FEISHU_VERIFY_TOKEN",
    "feishu.encrypt_key": "OPENBOT_DESKTOP_FEISHU_ENCRYPT_KEY",
    "embedding.api_key": "OPENBOT_DESKTOP_EMBEDDING_KEY",
    "reranker.api_key": "OPENBOT_DESKTOP_RERANKER_KEY",
    "tavily.api_key": "TAVILY_API_KEY",
}


def bind_secret_envs(values: dict) -> dict:
    """Accept only desktop-owned environment names, never arbitrary process variables."""
    model = values["model"]
    if not isinstance(model, dict) or not isinstance(model.get("primary"), dict):
        raise ValueError("模型格式无效。")
    if not isinstance(model.get("routing"), dict) or not isinstance(
        model["routing"].get("tiers"), dict
    ):
        raise ValueError("路由格式无效。")
    if model.get("fallback") is not None and not isinstance(model["fallback"], dict):
        raise ValueError("备选模型格式无效。")
    if any(not isinstance(value, dict) for value in model["routing"]["tiers"].values()):
        raise ValueError("路由模型格式无效。")
    if any(not isinstance(values.get(name), dict) for name in SECTIONS):
        raise ValueError("服务格式无效。")
    model["primary"]["api_key_env"] = MODEL_KEY_ENV
    if model.get("fallback"):
        model["fallback"]["api_key_env"] = SECRET_ENVS["model.fallback"]
    for tier, entry in model["routing"]["tiers"].items():
        entry["api_key_env"] = SECRET_ENVS[f"model.routing.{tier}"]
    values["telegram"]["bot_token_env"] = SECRET_ENVS["telegram.bot_token"]
    for name in ("app_id", "app_secret", "verification_token", "encrypt_key"):
        values["feishu"][f"{name}_env"] = SECRET_ENVS[f"feishu.{name}"]
    for name in ("embedding", "reranker"):
        values[name]["api_key_env"] = SECRET_ENVS[f"{name}.api_key"]
    return values


def configuration(settings: DesktopSettings, current: AppConfig) -> dict[str, Any]:
    state = settings.read()
    values = current.model_dump()
    values.update(state.services)
    values["model"]["primary"].update(
        provider=state.model.provider,
        model=state.model.model,
        base_url=state.model.base_url,
    )
    selected = bind_secret_envs({key: values[key] for key in SECTIONS})
    selected["telegram"]["webhook_secret"] = None
    return selected


def prepare_services(settings: DesktopSettings, current: AppConfig, payload: dict) -> DesktopState:
    if set(payload) - {"configuration", "secrets", "clear_secrets"}:
        raise ValueError("未知服务设置字段。")
    selected = payload.get("configuration")
    if not isinstance(selected, dict) or set(selected) != set(SECTIONS):
        raise ValueError("请提供完整服务配置。")
    # Revalidation uses fresh structures: never mutate the request or current config.
    selected = bind_secret_envs(deepcopy(selected))
    validate_service_values(selected)
    validated = AppConfig.model_validate(selected).model_dump()
    selected = bind_secret_envs({key: validated[key] for key in SECTIONS})
    state = settings.read()
    credentials = _merge_credentials(state, payload)
    primary = selected["model"]["primary"]
    model_key = credentials.pop("model.primary", state.model.api_key)
    if "model.primary" in payload.get("clear_secrets", []):
        model_key = ""
    model = DesktopModel(
        provider=primary["provider"],
        model=primary["model"],
        base_url=primary["base_url"] or state.model.base_url,
        api_key=model_key,
    )
    if not model.model.strip() or (not model.api_key and not is_local_endpoint(model.base_url)):
        raise ValueError("请填写主模型名称和远程服务密钥。")
    _validate_service_credentials(selected, credentials)
    selected["wechat"]["state_path"] = str(settings.data_dir / "data/wechat/ilink_state.json")
    if selected["wechat"]["enabled"]:
        from src.channels.adapters.wechat_state import WeChatStateStore

        if WeChatStateStore(selected["wechat"]["state_path"]).load() is None:
            raise ValueError("启用微信前请先扫码登录。")
    return state.model_copy(
        update={"services": selected, "secrets": credentials, "model": model, "configured": True}
    )


def _merge_credentials(state: DesktopState, payload: dict) -> dict[str, str]:
    credentials = dict(state.secrets)
    incoming = payload.get("secrets", {})
    clear = payload.get("clear_secrets", [])
    if not isinstance(incoming, dict) or not isinstance(clear, list):
        raise ValueError("凭据格式无效。")
    if any(key not in SECRET_ENVS for key in [*incoming, *clear]):
        raise ValueError("未知凭据字段。")
    for key, value in incoming.items():
        if not isinstance(value, str) or len(value) > 8192:
            raise ValueError("凭据格式无效。")
        if value.strip():
            credentials[key] = value.strip()
    for key in clear:
        credentials.pop(key, None)
    return credentials


def _validate_service_credentials(selected: dict, credentials: dict[str, str]) -> None:
    for entry, secret, required in [
        (selected["model"].get("fallback"), "model.fallback", True),
        *[
            (value, f"model.routing.{tier}", selected["model"]["routing"]["enabled"])
            for tier, value in selected["model"]["routing"]["tiers"].items()
        ],
    ]:
        if entry and entry.get("base_url"):
            DesktopModel(
                provider=entry["provider"], model=entry["model"], base_url=entry["base_url"]
            )
        if (
            required
            and entry
            and (
                not entry["model"].strip()
                or (
                    not credentials.get(secret)
                    and not is_local_endpoint(entry.get("base_url") or "")
                )
            )
        ):
            raise ValueError("备选或路由模型需要模型名称及独立密钥。")
    for name in ("embedding", "reranker"):
        if selected[name].get("base_url"):
            DesktopModel(base_url=selected[name]["base_url"])
    telegram = selected["telegram"]
    if telegram["webhook_secret"] is not None:
        raise ValueError("Webhook密钥请通过独立凭据字段填写。")
    if telegram["enabled"] and not credentials.get("telegram.bot_token"):
        raise ValueError("启用 Telegram 前需要配置 Bot Token。")
    if (
        telegram["enabled"]
        and telegram["mode"] == "webhook"
        and (not telegram["webhook_url"] or not credentials.get("telegram.webhook_secret"))
    ):
        raise ValueError("Telegram webhook模式需要公网地址及验证密钥。")
    if telegram["webhook_url"]:
        DesktopModel(base_url=telegram["webhook_url"])
    from src.desktop.wechat_login import _allowed_endpoint

    _allowed_endpoint(selected["wechat"]["api_base_url"])
    feishu = selected["feishu"]
    required = ("app_id", "app_secret") + (
        ("verification_token", "encrypt_key") if feishu["mode"] == "webhook" else ()
    )
    if feishu["enabled"] and any(not credentials.get(f"feishu.{name}") for name in required):
        raise ValueError("启用飞书前需要填写该连接模式的凭据。")
    for name in ("embedding", "reranker"):
        if selected[name]["enabled"] and not credentials.get(f"{name}.api_key"):
            raise ValueError("启用向量或重排服务前需要填写对应密钥。")


def imported_service_state(
    config: AppConfig, env_values: dict[str, str | None], previous: DesktopState
) -> DesktopState:
    """Convert only declared business secrets from an explicitly selected offline deployment."""
    sources = {
        "telegram.bot_token": config.telegram.bot_token_env,
        "feishu.app_id": config.feishu.app_id_env,
        "feishu.app_secret": config.feishu.app_secret_env,
        "feishu.verification_token": config.feishu.verification_token_env,
        "feishu.encrypt_key": config.feishu.encrypt_key_env,
        "embedding.api_key": config.embedding.api_key_env,
        "reranker.api_key": config.reranker.api_key_env,
        "tavily.api_key": "TAVILY_API_KEY",
    }
    if config.model.fallback:
        sources["model.fallback"] = config.model.fallback.api_key_env
    for tier, entry in config.model.routing.tiers.items():
        sources[f"model.routing.{tier}"] = entry.api_key_env
    credentials = {key: env_values.get(env, "") or "" for key, env in sources.items()}
    if config.telegram.webhook_secret:
        credentials["telegram.webhook_secret"] = config.telegram.webhook_secret
    primary = config.model.primary
    model = DesktopModel(
        provider=primary.provider,
        model=primary.model,
        base_url=primary.base_url
        or (
            "https://api.anthropic.com"
            if primary.provider == "anthropic"
            else "https://api.openai.com/v1"
        ),
        api_key=env_values.get(primary.api_key_env, "") or "",
    )
    values = bind_secret_envs({key: config.model_dump()[key] for key in SECTIONS})
    values["telegram"]["webhook_secret"] = None
    for channel in ("telegram", "feishu", "wechat"):
        values[channel]["enabled"] = False
    return previous.model_copy(
        update={
            "model": model,
            "services": values,
            "secrets": credentials,
            "permissions": {"bash": False, "code_executor": False},
            "tool_enabled": {"bash": False, "code_executor": False},
            "configured": bool(
                model.model and (model.api_key or is_local_endpoint(model.base_url))
            ),
        }
    )
