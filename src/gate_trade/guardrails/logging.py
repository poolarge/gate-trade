"""Structured logging facade for Gate Trade."""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog


def setup_logging(
    level: str = "INFO",
    json_format: bool = True,
    log_file: str | None = None,
) -> None:
    """Configure structlog for the process.

    Call once at startup. After that, import ``logger`` from this module.

    If *log_file* is provided, structured log lines are also appended to
    that file with rotation (10 MB max, 5 backups kept).
    """

    timestamper = structlog.processors.TimeStamper(fmt="iso", utc=True)
    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        timestamper,
    ]

    renderer: Any = (
        structlog.processors.JSONRenderer() if json_format
        else structlog.dev.ConsoleRenderer()
    )

    processors = shared_processors + [
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        renderer,
    ]

    if log_file:
        from logging.handlers import RotatingFileHandler
        from pathlib import Path

        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        _fh = RotatingFileHandler(
            log_file, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8",
        )

        def _write_to_file(_logger: Any, _method: str, event_dict: dict[str, Any]) -> dict[str, Any]:
            try:
                rendered = renderer(None, _method, event_dict)
                _fh.emit(logging.LogRecord("structlog", logging.INFO, "", 0, rendered, (), None))
            except Exception:
                pass
            return event_dict

        processors = shared_processors + [
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            _write_to_file,
            renderer,
        ]

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), logging.INFO)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(sys.stderr),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> structlog.BoundLogger:
    """Return a bound logger, optionally with a *name* key."""
    logger: structlog.BoundLogger = structlog.get_logger()
    if name:
        return logger.bind(logger_name=name)
    return logger


# Module-level convenience
logger: structlog.BoundLogger = structlog.get_logger()
