"""FastAPI app factory for OpenBot REST API."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from src.api.routes.chat import router as chat_router
from src.api.routes.conversations import router as conversations_router
from src.api.routes.knowledge import router as knowledge_router
from src.api.routes.metrics import router as metrics_router
from src.api.routes.schedules import router as schedules_router
from src.api.routes.settings import router as settings_router
from src.api.routes.tools import router as tools_router
from src.api.schemas import HealthResponse
from src.api.websocket import router as websocket_router
from src.core.logging import get_logger

if TYPE_CHECKING:
    from src.agent.agent import Agent
    from src.channels.adapters.web import WebAdapter
    from src.channels.hub import MsgHub
    from src.core.config import AppConfig
    from src.infrastructure.storage import Storage

logger = get_logger(__name__)


def create_api_app(
    *,
    agent: Agent | None = None,
    storage: Storage | None = None,
    config: AppConfig | None = None,
    msg_hub: MsgHub | None = None,
    web_adapter: WebAdapter | None = None,
    tool_registry: Any | None = None,
    monitor: Any | None = None,
) -> FastAPI:
    """Create a FastAPI app instance.

    The ``agent`` dependency is optional at startup time to allow running
    API smoke tests and wiring runtime dependencies in the application layer.
    """
    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        logger.info("api.starting")
        yield
        logger.info("api.stopping")

    app = FastAPI(title="OpenBot API", version="0.1.0", lifespan=lifespan)
    app.state.agent = agent
    app.state.storage = storage
    app.state.config = config
    app.state.msg_hub = msg_hub
    app.state.web_adapter = web_adapter
    app.state.tool_registry = tool_registry
    app.state.monitor = monitor

    cors_origins = config.api.cors_origins if config else ["*"]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(
        request: Request, exc: Exception,
    ) -> JSONResponse:
        logger.exception("api.unhandled_exception", path=str(request.url.path))
        return JSONResponse(
            status_code=500,
            content={"detail": f"Internal server error: {exc.__class__.__name__}"},
        )

    @app.get("/health", response_model=HealthResponse, tags=["system"])
    async def health() -> HealthResponse:
        return HealthResponse(status="ok")

    app.include_router(chat_router)
    app.include_router(conversations_router)
    app.include_router(knowledge_router)
    app.include_router(tools_router)
    app.include_router(schedules_router)
    app.include_router(metrics_router)
    app.include_router(settings_router)
    app.include_router(websocket_router)

    frontend_dist: Path | None = None
    frontend_index: Path | None = None
    if config and config.api.serve_frontend:
        frontend_dist = Path(config.api.frontend_dist)
        frontend_index = frontend_dist / "index.html"

    @app.get("/{full_path:path}", include_in_schema=False, response_model=None)
    async def spa_fallback(full_path: str):
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

    return app
