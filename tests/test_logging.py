import logging
from pathlib import Path

from lincona.config import LogLevel
from lincona.logging import configure_session_logger, session_log_path, _to_logging_level


def test_session_log_path_respects_base(tmp_path: Path) -> None:
    path = session_log_path("abc", tmp_path)
    assert path == tmp_path / "abc" / "log.txt"


def test_configure_session_logger_creates_file_and_logs(tmp_path: Path) -> None:
    session_id = "sess-1"
    logger = configure_session_logger(session_id, base_dir=tmp_path, log_level=LogLevel.INFO)

    logger.info("hello world")

    log_file = session_log_path(session_id, tmp_path)
    assert log_file.exists()
    content = log_file.read_text()
    assert "hello world" in content


def test_configure_session_logger_is_idempotent(tmp_path: Path) -> None:
    session_id = "sess-dup"
    logger1 = configure_session_logger(session_id, base_dir=tmp_path)
    logger2 = configure_session_logger(session_id, base_dir=tmp_path)

    assert logger1 is logger2
    assert len(logger1.handlers) == 1


def test_log_level_mapping(tmp_path: Path) -> None:
    session_id = "sess-level"
    logger = configure_session_logger(session_id, base_dir=tmp_path, log_level=LogLevel.DEBUG)

    assert logger.level == logging.DEBUG


def test_unknown_log_level_string_defaults_to_warning(tmp_path: Path) -> None:
    session_id = "sess-unknown"
    logger = configure_session_logger(session_id, base_dir=tmp_path, log_level="verbose")

    assert logger.level == logging.WARNING


def test_string_log_level_maps(tmp_path: Path) -> None:
    session_id = "sess-string"
    logger = configure_session_logger(session_id, base_dir=tmp_path, log_level="info")

    assert logger.level == logging.INFO


def test_to_logging_level_handles_enum_and_string():
    assert _to_logging_level(LogLevel.ERROR) == logging.ERROR
    assert _to_logging_level("debug") == logging.DEBUG
    assert _to_logging_level(123) == logging.WARNING
