"""Lifecycle/startup helpers for Application."""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any

import uvicorn

from src.agent.scheduling import AgentScheduler
from src.api import create_api_app
from src.channels.adapters.feishu import FeishuAdapter
from src.channels.adapters.feishu_long_connection import FeishuLongConnectionAdapter
from src.channels.adapters.telegram import TelegramAdapter
from src.channels.adapters.wechat import WeChatAdapter
from src.channels.adapters.wechat_state import WeChatStateStore
from src.core.logging import disable_db_logging, enable_db_logging, get_logger

logger = get_logger(__name__)


class UvicornServerNoSignals(uvicorn.Server):
    """Uvicorn server variant that lets the app own signal handling."""

    def install_signal_handlers(self) -> None:  # noqa: D401
        return None


async def start_application(app: Any) -> None:
    """Start all services owned by Application."""
    logger.info("app.starting")
    await app.database.initialize()
    enable_db_logging(app.storage.logs)
    if app.config.api.enabled:
        app.api_app = create_api_app(
            agent=app.agent,
            storage=app.storage,
            config=app.config,
            scheduler=app.scheduler,
            msg_hub=app.msg_hub,
            web_adapter=app.web_adapter,
            tool_registry=app.tool_registry,
            monitor=app.monitor,
            identity_service=app.identity_service,
        )
        uvicorn_config = uvicorn.Config(
            app=app.api_app,
            host=app.config.api.host,
            port=app.config.api.port,
            log_level=app.config.log.level.lower(),
            access_log=False,
        )
        app.api_server = UvicornServerNoSignals(uvicorn_config)
        app.api_task = asyncio.create_task(app.api_server.serve())
        await wait_for_api_ready(app)
    if app.api_app:
        app.api_app.state.wechat_runtime_status = "disabled"
    await start_telegram(app)
    await start_feishu(app)
    await start_wechat(app)
    app.scheduler = AgentScheduler(
        app.storage,
        app.agent,
        app.event_bus,
        app.msg_hub,
        config=app.config.scheduler,
    )
    await app.scheduler.start()
    if app.api_app:
        app.api_app.state.scheduler = app.scheduler
    logger.info("app.started")


async def stop_application(app: Any) -> None:
    """Gracefully stop all services."""
    logger.info("app.stopping")
    if app.api_server:
        app.api_server.should_exit = True
    if app.api_task:
        with contextlib.suppress(asyncio.CancelledError):
            await app.api_task
        app.api_task = None
        app.api_server = None
    if app.scheduler:
        await app.scheduler.stop()
    if app.feishu:
        await app.feishu.stop()
    if app.wechat:
        await app.wechat.stop()
    if app.telegram:
        await app.telegram.stop()
    disable_db_logging()
    await app.database.close()
    logger.info("app.stopped")


async def start_telegram(app: Any) -> None:
    """Start the Telegram adapter when configured."""
    if not app.config.telegram.enabled:
        logger.info("app.telegram_disabled")
        return
    missing_envs = app.config.telegram.missing_required_env_vars()
    if missing_envs:
        logger.warning("app.telegram_incomplete", missing_env_vars=missing_envs)
        return
    try:
        app.telegram = TelegramAdapter(app.config.telegram, app.msg_hub)
        app.msg_hub.register_adapter("telegram", app.telegram)
        await app.telegram.start()
        if app.api_app:
            app.api_app.state.telegram = app.telegram
        logger.info("app.telegram_ready", mode=app.config.telegram.mode)
    except Exception:
        app.telegram = None
        logger.exception("app.telegram_failed")


async def start_feishu(app: Any) -> None:
    """Start the Feishu adapter when configured."""
    if not app.config.feishu.enabled:
        logger.info("app.feishu_disabled")
        return
    missing_envs = app.config.feishu.missing_required_env_vars()
    if missing_envs:
        logger.warning("app.feishu_incomplete", missing_env_vars=missing_envs)
        return
    try:
        if app.config.feishu.mode == "long_connection":
            app.feishu = FeishuLongConnectionAdapter(app.config.feishu, app.msg_hub)
        else:
            app.feishu = FeishuAdapter(app.config.feishu, app.msg_hub)
        app.msg_hub.register_adapter("feishu", app.feishu)
        await app.feishu.start()
        if app.api_app and app.config.feishu.mode == "webhook":
            app.api_app.state.feishu = app.feishu
        logger.info(
            "app.feishu_ready",
            mode=app.config.feishu.mode,
            webhook_path="/webhook/feishu" if app.config.feishu.mode == "webhook" else None,
        )
    except Exception:
        app.feishu = None
        logger.exception("app.feishu_failed")


async def start_wechat(app: Any) -> None:
    """Start the WeChat adapter when configured."""
    if not app.config.wechat.enabled:
        logger.info("app.wechat_disabled")
        if app.api_app:
            app.api_app.state.wechat_runtime_status = "disabled"
        return
    try:
        state_store = WeChatStateStore(app.config.wechat.state_path)
        state = state_store.load()
        if state is None:
            logger.warning("app.wechat_login_required", state_path=app.config.wechat.state_path)
            if app.api_app:
                app.api_app.state.wechat_runtime_status = "login_required"
            return
        app.wechat = WeChatAdapter(
            app.config.wechat,
            app.msg_hub,
            state_store=state_store,
        )
        app.msg_hub.register_adapter("wechat", app.wechat)
        if app.api_app:
            app.api_app.state.wechat_runtime_status = "starting"
        await app.wechat.start()
        if app.api_app:
            app.api_app.state.wechat = app.wechat
            app.api_app.state.wechat_runtime_status = "ready"
        logger.info(
            "app.wechat_ready",
            mode=app.config.wechat.mode,
            account_id=state.account_id,
        )
    except Exception:
        app.wechat = None
        if app.api_app:
            app.api_app.state.wechat_runtime_status = "degraded"
        logger.exception("app.wechat_failed")


async def wait_for_api_ready(app: Any, timeout: float = 5.0) -> None:
    """Wait for Uvicorn startup and fail fast on startup errors."""
    if not app.api_server:
        return
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not app.api_server.started:
        if app.api_task and app.api_task.done():
            exc = app.api_task.exception()
            if exc is not None:
                raise RuntimeError("API server failed to start") from exc
            raise RuntimeError("API server exited before becoming ready")
        if loop.time() >= deadline:
            logger.warning(
                "app.api_start_timeout",
                host=app.config.api.host,
                port=app.config.api.port,
            )
            return
        await asyncio.sleep(0.05)
    logger.info(
        "app.api_ready",
        host=app.config.api.host,
        port=app.config.api.port,
    )
