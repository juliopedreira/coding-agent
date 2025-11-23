import logging
from pathlib import Path

from lincona.config import LogLevel
from lincona.logging import configure_session_logger, session_log_path


def test_session_log_path_respects_base(tmp_path: Path) -> None:
    path = session_log_path("abc", tmp_path)
    assert path == tmp_path / "abc.log"


def test_configure_session_logger_creates_file_and_logs(tmp_path: Path) -> None:
    session_id = "sess-1"
    logger = configure_session_logger(session_id, base_dir=tmp_path, log_level=LogLevel.INFO, max_bytes=1024)

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


def test_truncates_oversized_log(tmp_path: Path) -> None:
    session_id = "sess-large"
    log_file = session_log_path(session_id, tmp_path)
    log_file.parent.mkdir(parents=True, exist_ok=True)
    log_file.write_text("x" * 200, encoding="utf-8")

    configure_session_logger(session_id, base_dir=tmp_path, max_bytes=100)

    assert log_file.stat().st_size == 0


def test_log_level_mapping(tmp_path: Path) -> None:
    session_id = "sess-level"
    logger = configure_session_logger(session_id, base_dir=tmp_path, log_level=LogLevel.DEBUG)

    assert logger.level == logging.DEBUG


def test_does_not_truncate_when_below_limit(tmp_path: Path) -> None:
    session_id = "sess-small"
    log_file = session_log_path(session_id, tmp_path)
    log_file.parent.mkdir(parents=True, exist_ok=True)
    log_file.write_text("abc", encoding="utf-8")

    configure_session_logger(session_id, base_dir=tmp_path, max_bytes=1024)

    assert log_file.read_text() == "abc"


def test_unknown_log_level_string_defaults_to_warning(tmp_path: Path) -> None:
    session_id = "sess-unknown"
    logger = configure_session_logger(session_id, base_dir=tmp_path, log_level="verbose")

    assert logger.level == logging.WARNING
