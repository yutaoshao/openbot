"""Structured logging setup with structlog.

Provides colorized console output for development and JSON format for
production.  Integrates with ``src.core.trace.TraceContext`` to auto-inject
trace_id, interaction_id, and iteration into every log entry.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import re
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from src.infrastructure.storage import LogRepo

# ---------------------------------------------------------------------------
# PII patterns to sanitize
# ---------------------------------------------------------------------------

_PII_PATTERNS = [
    # Phone numbers — require leading + or at least 10 consecutive digits with separators
    (re.compile(r"\+\d{1,3}[-.\s]?\(?\d{2,4}\)?[-.\s]?\d{3,4}[-.\s]?\d{3,4}\b"), "[PHONE]"),
    # Email addresses
    (re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"), "[EMAIL]"),
    # API keys / tokens (long hex or base64 strings)
    (re.compile(r"\b(?:sk-|tok_|key_|Bearer\s)[A-Za-z0-9_-]{20,}\b"), "[API_KEY]"),
]


# ---------------------------------------------------------------------------
# Structlog processors
# ---------------------------------------------------------------------------


def _inject_trace_context(
    logger: structlog.types.WrappedLogger,
    method: str,
    event_dict: dict,
) -> dict:
    """Auto-inject trace_id, interaction_id, iteration from TraceContext."""
    from src.core.trace import current_trace

    ctx = current_trace()
    if ctx:
        for key, value in ctx.to_dict().items():
            event_dict.setdefault(key, value)
    return event_dict


def _sanitize_pii(
    logger: structlog.types.WrappedLogger,
    method: str,
    event_dict: dict,
) -> dict:
    """Redact PII patterns from string values in the log entry."""
    for key, value in event_dict.items():
        if isinstance(value, str) and len(value) > 8:
            for pattern, replacement in _PII_PATTERNS:
                value = pattern.sub(replacement, value)
            event_dict[key] = value
    return event_dict


# ---------------------------------------------------------------------------
# Async DB log writer
# ---------------------------------------------------------------------------

# Structured event names that should be persisted to DB.
# Non-agent events (app lifecycle, third-party) are excluded to reduce noise.
_PERSIST_EVENTS = {
    "task_received",
    "session_started",
    "session_ended",
    "guardrail_blocked",
    "thought_step",
    "decision_made",
    "reflection_updated",
    "plan_generated",
    "tool_called",
    "llm_requested",
    "llm_completed",
    "memory_retrieved",
    "skill_loaded",
    "task_finished",
    "task_failed",
}

# Singleton reference for the DB writer (set by enable_db_logging)
_db_writer: _LogDBWriter | None = None


class _LogDBWriter:
    """Batched async writer that flushes logs to the ``logs`` table.

    Logs are queued from the structlog processor (sync context) and
    flushed periodically by an asyncio task to avoid blocking.
    """

    def __init__(self, log_repo: LogRepo, flush_interval: float = 1.0) -> None:
        self._repo = log_repo
        self._queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=10000)
        self._flush_interval = flush_interval
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._flush_loop())

    def stop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
        # Schedule a final flush to drain remaining queued logs
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._flush())
        except RuntimeError:
            pass  # No running loop (shutdown)

    def enqueue(self, entry: dict[str, Any]) -> None:
        with contextlib.suppress(asyncio.QueueFull):
            self._queue.put_nowait(entry)

    async def _flush_loop(self) -> None:
        while True:
            await asyncio.sleep(self._flush_interval)
            await self._flush()

    async def _flush(self) -> None:
        batch: list[dict[str, Any]] = []
        while not self._queue.empty():
            try:
                batch.append(self._queue.get_nowait())
            except asyncio.QueueEmpty:
                break
        if not batch:
            return
        with contextlib.suppress(Exception):
            await self._repo.insert_batch(batch)


def _persist_to_db(
    logger: structlog.types.WrappedLogger,
    method: str,
    event_dict: dict,
) -> dict:
    """Structlog processor that enqueues matching events for DB persistence."""
    global _db_writer  # noqa: PLW0602
    if _db_writer is None:
        return event_dict

    event_name = event_dict.get("event", "")
    if event_name not in _PERSIST_EVENTS:
        return event_dict

    # Extract structured fields, put the rest into data JSON
    known_keys = {
        "event",
        "level",
        "timestamp",
        "surface",
        "trace_id",
        "interaction_id",
        "platform",
        "iteration",
        "logger",
        "logger_name",
    }
    extra = {k: v for k, v in event_dict.items() if k not in known_keys}
    data_json = json.dumps(extra, ensure_ascii=False, default=str) if extra else None

    _db_writer.enqueue(
        {
            "timestamp": event_dict.get("timestamp", ""),
            "level": event_dict.get("level", "info"),
            "event": event_name,
            "surface": event_dict.get("surface"),
            "trace_id": event_dict.get("trace_id"),
            "interaction_id": event_dict.get("interaction_id"),
            "platform": event_dict.get("platform"),
            "iteration": event_dict.get("iteration"),
            "data": data_json,
        }
    )

    return event_dict


def enable_db_logging(log_repo: LogRepo) -> None:
    """Enable async DB log persistence. Call after database is initialized."""
    global _db_writer
    _db_writer = _LogDBWriter(log_repo)
    _db_writer.start()


def disable_db_logging() -> None:
    """Stop DB log persistence."""
    global _db_writer
    if _db_writer:
        _db_writer.stop()
        _db_writer = None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def setup_logging(
    level: str = "INFO",
    fmt: str = "console",
    log_file: str | None = None,
    max_bytes: int = 10 * 1024 * 1024,  # 10 MB
    backup_count: int = 5,
) -> None:
    """Initialize structlog with trace context injection and PII sanitization.

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR).
        fmt: Output format — "console" (colorized) or "json".
        log_file: Optional file path for log rotation.
        max_bytes: Max log file size before rotation (default 10 MB).
        backup_count: Number of rotated log files to keep.
    """
    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=False),
        _inject_trace_context,
        _sanitize_pii,
        _persist_to_db,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
    ]

    if fmt == "json":
        renderer: structlog.types.Processor = structlog.processors.JSONRenderer(
            ensure_ascii=False,
        )
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=sys.stdout.isatty())

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    # Console handler (always)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(console_handler)
    root_logger.setLevel(level.upper())

    # File handler (optional, always JSON for machine parsing)
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)

        json_formatter = structlog.stdlib.ProcessorFormatter(
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                structlog.processors.JSONRenderer(ensure_ascii=False),
            ],
        )
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        file_handler.setFormatter(json_formatter)
        root_logger.addHandler(file_handler)

    # Suppress noisy third-party loggers
    for name in ("httpx", "httpcore", "telegram", "apscheduler"):
        logging.getLogger(name).setLevel(logging.WARNING)


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Get a named structured logger."""
    return structlog.get_logger(name)
