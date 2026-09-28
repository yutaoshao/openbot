"""Lifecycle/startup helpers for Application."""

from __future__ import annotations

import asyncio
import contextlib
from typing import TYPE_CHECKING

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
_IDLE_PRUNE_INTERVAL_SECONDS = 60

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from .container import Application


class UvicornServerNoSignals(uvicorn.Server):
    """Uvicorn server variant that lets the app own signal handling."""

    def install_signal_handlers(self) -> None:  # noqa: D401
        return None


async def start_application(app: Application) -> None:
    """Start all services owned by Application."""
    logger.info("app.starting")
    try:
        await _start_services(app)
    except BaseException:
        try:
            await stop_application(app)
        except Exception:
            logger.exception("app.startup_cleanup_failed")
        raise
    logger.info("app.started")


async def _start_services(app: Application) -> None:
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
            settings_service=app.settings_service,
            application=app,
        )
        uvicorn_config = uvicorn.Config(
            app=app.api_app,
            host=app.config.api.host,
            port=app.config.api.port,
            log_level=app.config.log.level.lower(),
            access_log=False,
        )
        app.api_server = UvicornServerNoSignals(uvicorn_config)
        app.api_task = asyncio.create_task(_serve_api(app.api_server))
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
    await start_housekeeping(app)
    if app.api_app:
        app.api_app.state.scheduler = app.scheduler


async def _serve_api(server: UvicornServerNoSignals) -> None:
    """Keep Uvicorn's process exit inside the application's startup boundary."""
    try:
        await server.serve()
    except SystemExit as exc:
        raise RuntimeError(
            f"API server exited at {server.config.host}:{server.config.port} (status {exc.code})"
        ) from exc


async def stop_application(app: Application) -> None:
    """Gracefully stop all services."""
    logger.info("app.stopping")
    errors: list[Exception] = []
    await _stop_component("api", lambda: _stop_api(app), errors)
    await _stop_component("housekeeping", lambda: stop_housekeeping(app), errors)
    if app.scheduler:
        await _stop_component("scheduler", app.scheduler.stop, errors)
    if app.feishu:
        await _stop_component("feishu", app.feishu.stop, errors)
    if app.wechat:
        await _stop_component("wechat", app.wechat.stop, errors)
    if app.telegram:
        await _stop_component("telegram", app.telegram.stop, errors)
    await _stop_component("post_turn_memory", app.post_turn_memory.stop, errors)
    try:
        disable_db_logging()
    except Exception as exc:
        errors.append(exc)
        logger.exception("app.cleanup_failed", component="db_logging")
    await _stop_component("database", app.database.close, errors)
    logger.info("app.stopped")
    if errors:
        raise ExceptionGroup("Application shutdown failed", errors)


async def _stop_api(app: Application) -> None:
    if app.api_server:
        app.api_server.should_exit = True
    try:
        if app.api_task:
            if app.api_server and not app.api_server.started:
                app.api_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await app.api_task
    finally:
        app.api_task = None
        app.api_server = None


async def _stop_component(
    name: str, stop: Callable[[], Awaitable[None]], errors: list[Exception]
) -> None:
    try:
        await stop()
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.exception("app.cleanup_failed", component=name)
        errors.append(exc)


async def start_housekeeping(app: Application) -> None:
    """Start background housekeeping tasks."""
    if app.housekeeping_task and not app.housekeeping_task.done():
        return
    app.housekeeping_task = asyncio.create_task(
        _run_housekeeping_loop(app),
        name="openbot-housekeeping",
    )


async def stop_housekeeping(app: Application) -> None:
    """Stop background housekeeping tasks."""
    task = app.housekeeping_task
    if task is None:
        return
    try:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
    finally:
        app.housekeeping_task = None


async def _run_housekeeping_loop(app: Application) -> None:
    while True:
        await asyncio.sleep(_IDLE_PRUNE_INTERVAL_SECONDS)
        await _prune_idle_conversations(app)


async def _prune_idle_conversations(app: Application) -> None:
    try:
        await app.conversation_manager.prune_idle_conversations()
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("app.housekeeping_prune_failed")


async def start_telegram(app: Application) -> None:
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
        await _cleanup_failed_adapter(app, "telegram", app.telegram)
        app.telegram = None
        logger.exception("app.telegram_failed")


async def start_feishu(app: Application) -> None:
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
        await _cleanup_failed_adapter(app, "feishu", app.feishu)
        app.feishu = None
        logger.exception("app.feishu_failed")


async def start_wechat(app: Application) -> None:
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
        await _cleanup_failed_adapter(app, "wechat", app.wechat)
        app.wechat = None
        if app.api_app:
            app.api_app.state.wechat_runtime_status = "degraded"
        logger.exception("app.wechat_failed")


async def _cleanup_failed_adapter(
    app: Application,
    platform: str,
    adapter: TelegramAdapter | FeishuAdapter | FeishuLongConnectionAdapter | WeChatAdapter | None,
) -> None:
    if adapter is None:
        return
    try:
        await adapter.stop()
    except Exception:
        logger.exception("app.adapter_startup_cleanup_failed", platform=platform)
    finally:
        app.msg_hub.unregister_adapter(platform, adapter)


async def wait_for_api_ready(app: Application, timeout: float = 5.0) -> None:
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
            raise TimeoutError(
                f"API server did not become ready at {app.config.api.host}:{app.config.api.port}"
            )
        await asyncio.sleep(0.05)
    logger.info(
        "app.api_ready",
        host=app.config.api.host,
        port=app.config.api.port,
    )
