"""FastAPI app factory for OpenBot REST API."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from src.agent.coordination import UserExecutionCoordinator
from src.api.local_access import enforce_local_request
from src.api.routes.chat import router as chat_router
from src.api.routes.conversations import router as conversations_router
from src.api.routes.identities import router as identities_router
from src.api.routes.knowledge import router as knowledge_router
from src.api.routes.logs import router as logs_router
from src.api.routes.metrics import router as metrics_router
from src.api.routes.schedules import router as schedules_router
from src.api.routes.settings import router as settings_router
from src.api.routes.tools import router as tools_router
from src.api.routes.webhook import router as webhook_router
from src.api.runtime_status import build_runtime_status
from src.api.schemas import HealthResponse
from src.api.websocket import router as websocket_router
from src.core.logging import get_logger

if TYPE_CHECKING:
    from src.agent.agent import Agent
    from src.agent.scheduling import AgentScheduler
    from src.application.container import Application
    from src.application.settings import SettingsService
    from src.channels.adapters.web import WebAdapter
    from src.channels.hub import MsgHub
    from src.core.config import AppConfig
    from src.identity.service import IdentityService
    from src.infrastructure.storage import Storage

logger = get_logger(__name__)

_DEFAULT_CORS_ORIGINS = [
    "http://127.0.0.1:8000",
    "http://localhost:8000",
    "http://127.0.0.1:5173",
    "http://localhost:5173",
]


@asynccontextmanager
async def _api_lifespan(_app: FastAPI):
    logger.info("api.starting")
    yield
    logger.info("api.stopping")


async def _handle_unexpected_error(request: Request, _exc: Exception) -> JSONResponse:
    logger.exception("api.unhandled_exception", path=str(request.url.path))
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )


def _create_base_app(config: AppConfig | None) -> FastAPI:
    app = FastAPI(title="OpenBot API", version="0.1.0", lifespan=_api_lifespan)
    cors_origins = config.api.cors_origins if config else _DEFAULT_CORS_ORIGINS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.middleware("http")(enforce_local_request)
    app.add_exception_handler(Exception, _handle_unexpected_error)
    return app


def _request_execution_coordinator(application: Application | None) -> UserExecutionCoordinator:
    execution_coordinator = getattr(application, "execution_coordinator", None)
    if execution_coordinator is None:
        return UserExecutionCoordinator()
    return execution_coordinator


def create_api_app(
    *,
    agent: Agent | None = None,
    storage: Storage | None = None,
    config: AppConfig | None = None,
    scheduler: AgentScheduler | None = None,
    msg_hub: MsgHub | None = None,
    web_adapter: WebAdapter | None = None,
    tool_registry: Any | None = None,
    monitor: Any | None = None,
    identity_service: IdentityService | None = None,
    settings_service: SettingsService | None = None,
    application: Application | None = None,
) -> FastAPI:
    """Create a FastAPI app instance.

    The ``agent`` dependency is optional at startup time to allow running
    API smoke tests and wiring runtime dependencies in the application layer.
    """
    app = _create_base_app(config)
    app.state.agent = agent
    app.state.storage = storage
    app.state.config = config
    app.state.runtime_config = config
    app.state.scheduler = scheduler
    app.state.msg_hub = msg_hub
    app.state.web_adapter = web_adapter
    app.state.tool_registry = tool_registry
    app.state.monitor = monitor
    app.state.identity_service = identity_service
    app.state.settings_service = settings_service
    app.state.application = application
    app.state.execution_coordinator = _request_execution_coordinator(application)
    app.state.restart_required = False
    app.state.restart_reasons = []
    # Populated later by Application.start() for webhook routes
    app.state.telegram = None
    app.state.feishu = None
    app.state.wechat = None
    app.state.wechat_runtime_status = None
    _register_api_routes(app)
    _register_frontend_route(app, config)
    return app


def _register_api_routes(app: FastAPI) -> None:
    @app.get("/health", response_model=HealthResponse, tags=["system"])
    async def health() -> HealthResponse:
        return HealthResponse(status="ok", runtime=build_runtime_status(app))

    for api_router in (
        chat_router,
        conversations_router,
        identities_router,
        knowledge_router,
        logs_router,
        tools_router,
        schedules_router,
        metrics_router,
        settings_router,
        websocket_router,
        webhook_router,
    ):
        app.include_router(api_router)


def _register_frontend_route(app: FastAPI, config: AppConfig | None) -> None:
    frontend_dist, frontend_index = _frontend_paths(config)

    @app.get("/{full_path:path}", include_in_schema=False, response_model=None)
    async def spa_fallback(full_path: str) -> FileResponse | JSONResponse:
        if full_path.startswith("api/"):
            return JSONResponse(status_code=404, content={"detail": "Not found"})
        if frontend_dist and full_path:
            resolved_dist = frontend_dist.resolve()
            candidate = (frontend_dist / full_path).resolve()
            if resolved_dist in candidate.parents and candidate.is_file():
                return FileResponse(candidate)
        if frontend_index and frontend_index.exists():
            return FileResponse(frontend_index)
        return JSONResponse(
            status_code=404,
            content={"detail": "Frontend assets not built. Run frontend build first."},
        )


def _frontend_paths(config: AppConfig | None) -> tuple[Path | None, Path | None]:
    if config is None or not config.api.serve_frontend:
        return None, None
    frontend_dist = Path(config.api.frontend_dist)
    return frontend_dist, frontend_dist / "index.html"
