"""Structured logging setup with structlog.

Provides colorized console output for development and JSON format for
production.  Integrates with ``src.core.trace.TraceContext`` to auto-inject
trace_id, interaction_id, and iteration into every log entry.
"""

from __future__ import annotations

import logging
import re
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

import structlog

# ---------------------------------------------------------------------------
# PII patterns to sanitize
# ---------------------------------------------------------------------------

_PII_PATTERNS = [
    # Phone numbers (international)
    (re.compile(r"\b(\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b"), "[PHONE]"),
    # Email addresses
    (re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"), "[EMAIL]"),
    # API keys / tokens (long hex or base64 strings)
    (re.compile(r"\b(?:sk-|tok_|key_)[A-Za-z0-9_-]{20,}\b"), "[API_KEY]"),
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
