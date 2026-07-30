"""
Unit tests for structured logging + correlation ID (docs/phase-3.1, Step 3.2).

JSON records must be valid JSON carrying the correlation ID; the text formatter must include
it too; configure_logging must honour LOG_FORMAT / LOG_LEVEL from settings.
"""

from __future__ import annotations

import json
import logging

import pytest

from config.settings import get_settings
from observability import configure_logging, get_correlation_id, set_correlation_id
from observability.logging import JsonFormatter, TextFormatter


def _record(msg: str = "hello", **extra) -> logging.LogRecord:
    return logging.LogRecord(
        name="test.logger",
        level=logging.INFO,
        pathname="f.py",
        lineno=1,
        msg=msg,
        args=None,
        exc_info=None,
    )


def test_json_formatter_includes_correlation_id() -> None:
    set_correlation_id("corr-123")
    out = JsonFormatter().format(_record("hi"))
    data = json.loads(out)
    assert data["correlation_id"] == "corr-123"
    assert data["message"] == "hi"
    assert data["level"] == "INFO"
    assert data["logger"] == "test.logger"
    set_correlation_id(None)


def test_json_formatter_includes_structured_extra() -> None:
    set_correlation_id(None)
    record = _record("job done")
    record.job_id = "abc"  # structured extra
    data = json.loads(JsonFormatter().format(record))
    assert data["job_id"] == "abc"
    assert data["correlation_id"] is None


def test_text_formatter_includes_correlation_id() -> None:
    set_correlation_id("corr-xyz")
    line = TextFormatter().format(_record("running"))
    assert "corr-xyz" in line
    assert "running" in line
    set_correlation_id(None)


def test_set_get_correlation_id_roundtrip() -> None:
    set_correlation_id("abc")
    assert get_correlation_id() == "abc"
    set_correlation_id(None)


def test_configure_logging_honours_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOG_FORMAT", "json")
    monkeypatch.setenv("LOG_LEVEL", "WARNING")
    get_settings.cache_clear()
    configure_logging()
    root = logging.getLogger()
    assert root.level == logging.WARNING
    assert isinstance(root.handlers[0].formatter, JsonFormatter)

    monkeypatch.setenv("LOG_FORMAT", "text")
    get_settings.cache_clear()
    configure_logging()
    assert isinstance(logging.getLogger().handlers[0].formatter, TextFormatter)
