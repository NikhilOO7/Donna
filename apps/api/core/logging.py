"""
Structured logging configuration using structlog.

Produces JSON logs in production (machine-parseable for log aggregation)
and colored console logs in development (human-readable).

Request-ID is automatically propagated to all log entries via contextvars.
"""

import logging
import logging.config
import sys
from pathlib import Path

import structlog
from structlog.contextvars import merge_contextvars

from apps.api.core.config import settings


def configure_logging() -> None:
    """Configure structlog + stdlib logging for the application.

    Call this once at startup before any logger is used.
    """
    log_level = getattr(logging, settings.log_level.upper(), logging.INFO)
    use_json = settings.log_format == "json"

    # Ensure logs directory exists
    logs_dir = Path("logs")
    logs_dir.mkdir(exist_ok=True)

    # Shared structlog processors (run on every log event)
    shared_processors: list = [
        merge_contextvars,                          # pulls request_id, etc. from contextvars
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.stdlib.ExtraAdder(),
    ]

    if use_json:
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=True)

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    # Configure stdlib logging to route through structlog's formatter
    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    console_handler.setLevel(log_level)

    # File handler (rotating)
    from logging.handlers import RotatingFileHandler

    file_handler = RotatingFileHandler(
        logs_dir / "app.log",
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.DEBUG)

    # Error file handler
    error_handler = RotatingFileHandler(
        logs_dir / "error.log",
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
    )
    error_handler.setFormatter(formatter)
    error_handler.setLevel(logging.ERROR)

    # Apply to root logger
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(console_handler)
    root.addHandler(file_handler)
    root.addHandler(error_handler)
    root.setLevel(log_level)

    # Quiet noisy third-party loggers
    for name in ("httpcore", "httpx", "urllib3", "asyncio"):
        logging.getLogger(name).setLevel(logging.WARNING)


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Get a structlog logger. Drop-in replacement for logging.getLogger()."""
    return structlog.get_logger(name)
