"""Authenticated desktop service settings and finite WeChat login sessions."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Body, HTTPException, Request

from src.desktop.service import pause_for_restart
from src.desktop.services import SECRET_ENVS, configuration, prepare_services
from src.desktop.wechat_login import DesktopWeChatLogin

router = APIRouter(prefix="/api/desktop", tags=["desktop"])


def _login(request: Request) -> DesktopWeChatLogin:
    service = request.app.state.desktop_service
    if not hasattr(service, "wechat_login"):
        service.wechat_login = DesktopWeChatLogin(service.settings)
    return service.wechat_login


@router.get("/services")
async def get_services(request: Request) -> dict:
    from src.channels.adapters.wechat_state import WeChatStateStore

    settings = request.app.state.desktop_service.settings
    state = settings.read()
    return {
        "configuration": configuration(settings, request.app.state.config),
        "secrets": [
            {
                "key": key,
                "is_set": bool(
                    state.model.api_key if key == "model.primary" else state.secrets.get(key)
                ),
            }
            for key in SECRET_ENVS
        ],
        "wechat": {
            "logged_in": WeChatStateStore(
                str(settings.data_dir / "data/wechat/ilink_state.json")
            ).load()
            is not None
        },
    }


@router.put("/services")
async def put_services(request: Request, payload: Annotated[Any, Body(...)]) -> dict:
    settings = request.app.state.desktop_service.settings
    try:
        if not isinstance(payload, dict):
            raise ValueError()
        selected = prepare_services(settings, request.app.state.config, payload)
    except (ValueError, TypeError, KeyError):
        # Validation exceptions contain input values, including credentials.
        raise HTTPException(
            422, "服务配置无效，请检查模型、地址、启用渠道的凭据和微信登录状态。"
        ) from None
    if _login(request).active:
        raise HTTPException(409, "请先完成或取消微信扫码登录。")
    if not pause_for_restart(request.app):
        raise HTTPException(409, "还有对话或任务执行或排队，请结束后再保存。")
    try:
        settings.save(selected)
        await request.app.state.application.request_restart()
    except BaseException:
        request.app.state.execution_coordinator.resume()
        raise
    return {"status": "saved", "requires_restart": True}


@router.post("/wechat/login")
async def start_wechat_login(request: Request) -> dict:
    if request.app.state.config.wechat.enabled:
        raise HTTPException(409, "请先关闭微信渠道并保存重启，再更换登录账号。")
    try:
        return await _login(request).start(request.app.state.config.wechat.api_base_url)
    except Exception:
        raise HTTPException(502, "无法获取微信二维码，请检查网络后重试。") from None


@router.get("/wechat/login/{session_id}")
async def get_wechat_login(request: Request, session_id: str) -> dict:
    result = _login(request).snapshot(session_id)
    if result is None:
        raise HTTPException(404, "扫码会话不存在。")
    return result


@router.delete("/wechat/login/{session_id}")
async def cancel_wechat_login(request: Request, session_id: str) -> dict:
    login = _login(request)
    if login.snapshot(session_id) is None:
        raise HTTPException(404, "扫码会话不存在。")
    if not await login.cancel(session_id):
        raise HTTPException(404, "扫码会话不存在。")
    return login.snapshot(session_id)
