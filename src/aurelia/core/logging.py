"""Structured logging configuration using structlog."""

from __future__ import annotations

import logging
import sys

import structlog


def configure_logging(json_output: bool = False, level: str = "INFO") -> None:
    """Configure structlog for Aurelia.

    Args:
        json_output: If True, output JSON; otherwise pretty console output.
        level: Log level (DEBUG, INFO, WARNING, ERROR).
    """
    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.stdlib.add_logger_name,
    ]

    if json_output:
        # JSON output for production/log aggregation
        processors = shared_processors + [
            structlog.processors.JSONRenderer()
        ]
    else:
        # Pretty console output for development
        processors = shared_processors + [
            structlog.dev.ConsoleRenderer(colors=True)
        ]

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Configure stdlib logging - force reconfiguration
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper()))

    # Remove existing handlers and add new one
    for handler in root.handlers[:]:
        root.removeHandler(handler)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(message)s"))
    root.addHandler(handler)
