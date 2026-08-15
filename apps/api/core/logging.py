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
        merge_contextvars,  # pulls request_id, etc. from contextvars
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
    #  - neo4j: logs idempotent "index/constraint already exists" notices every startup
    #  - sentence_transformers: logs "Use pytorch device... / Load pretrained..." per model
    for name in (
        "httpcore",
        "httpx",
        "urllib3",
        "asyncio",
        "neo4j",
        "neo4j.notifications",
        "sentence_transformers",
        "sentence_transformers.SentenceTransformer",
    ):
        logging.getLogger(name).setLevel(logging.WARNING)

    # SQLAlchemy: route through structlog (propagate) and keep it quiet unless
    # DB_ECHO is on. Pinning the level here also prevents the double-emit you
    # get when the engine logger logs directly *and* propagates to root.
    sql_level = logging.INFO if settings.db_echo else logging.WARNING
    for name in ("sqlalchemy.engine", "sqlalchemy.pool", "sqlalchemy.dialects"):
        sql_logger = logging.getLogger(name)
        sql_logger.setLevel(sql_level)
        sql_logger.handlers.clear()
        sql_logger.propagate = True


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Get a structlog logger. Drop-in replacement for logging.getLogger()."""
    return structlog.get_logger(name)


# ---------------------------------------------------------------------------
# Rate-limited warnings for best-effort paths
# ---------------------------------------------------------------------------
# Degradation paths (cache miss-on-error, lock falling back to process-local,
# pub/sub publish failure) must never raise — but logging them at DEBUG means
# that in production, where the level is INFO, they log *nowhere*. A subsystem
# silently degrading with no operator signal is exactly the failure shape that
# has already cost this codebase real debugging time.
#
# These paths are also per-request, so an unconditional warning would flood.
# `warn_throttled` emits at WARNING at most once per interval per key, with a
# suppression count so the true rate is still visible.

_THROTTLE_STATE: dict[str, tuple[float, int]] = {}
_DEFAULT_THROTTLE_SECONDS = 60.0


def warn_throttled(
    logger_obj,
    key: str,
    message: str,
    interval_seconds: float = _DEFAULT_THROTTLE_SECONDS,
) -> None:
    """Log ``message`` at WARNING at most once per ``interval_seconds`` per ``key``.

    Suppressed occurrences are counted and reported on the next emission, so a
    persistently failing subsystem reads as
    ``"... (repeated 412x in the last 60s)"`` rather than either flooding the
    log or vanishing from it.
    """
    import time as _time

    now = _time.monotonic()
    last, suppressed = _THROTTLE_STATE.get(key, (0.0, 0))

    if now - last < interval_seconds:
        _THROTTLE_STATE[key] = (last, suppressed + 1)
        return

    if suppressed:
        message = (
            f"{message} (repeated {suppressed}x in the last {interval_seconds:.0f}s)"
        )
    _THROTTLE_STATE[key] = (now, 0)

    try:
        logger_obj.warning(message)
    except Exception:
        pass  # logging must never be the thing that breaks a degradation path
