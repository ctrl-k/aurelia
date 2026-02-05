"""Tests for structured logging configuration."""

from __future__ import annotations

import io
import json
import logging

import pytest
import structlog

from aurelia.core.logging import configure_logging


@pytest.fixture(autouse=True)
def reset_logging() -> None:
    """Reset logging configuration between tests."""
    # Reset structlog
    structlog.reset_defaults()
    # Remove all handlers from root logger
    root = logging.getLogger()
    for handler in root.handlers[:]:
        root.removeHandler(handler)
    root.setLevel(logging.WARNING)  # Reset to default


def test_configure_logging_console_output() -> None:
    """Test that console output mode works."""
    configure_logging(json_output=False, level="INFO")

    # Verify root level is set
    assert logging.getLogger().level == logging.INFO

    # Verify handler is attached
    assert len(logging.getLogger().handlers) == 1


def test_configure_logging_json_output() -> None:
    """Test that JSON output mode produces valid JSON."""
    # Capture output via a custom handler
    captured = io.StringIO()

    configure_logging(json_output=True, level="INFO")

    # Replace the stdout handler with our capturing one
    root = logging.getLogger()
    for handler in root.handlers[:]:
        root.removeHandler(handler)
    handler = logging.StreamHandler(captured)
    handler.setFormatter(logging.Formatter("%(message)s"))
    root.addHandler(handler)

    # Use structlog to log a message
    log = structlog.get_logger("test_json")
    log.info("test message", key="value")

    output = captured.getvalue()

    # Verify JSON output
    assert output.strip()
    data = json.loads(output.strip())
    assert data["event"] == "test message"
    assert data["key"] == "value"
    assert data["level"] == "info"
    assert "timestamp" in data


def test_configure_logging_level_debug() -> None:
    """Test that DEBUG level is set correctly."""
    configure_logging(json_output=False, level="DEBUG")
    assert logging.getLogger().level == logging.DEBUG


def test_configure_logging_level_warning() -> None:
    """Test that WARNING level is set correctly."""
    configure_logging(json_output=False, level="WARNING")
    assert logging.getLogger().level == logging.WARNING


def test_configure_logging_level_error() -> None:
    """Test that ERROR level is set correctly."""
    configure_logging(json_output=False, level="ERROR")
    assert logging.getLogger().level == logging.ERROR
