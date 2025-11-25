"""Logging setup for Lincona sessions.

Each session writes to ``~/.lincona/sessions/<session>/log.txt``. The logger is
isolated (no propagation) and avoids duplicate handlers across repeated
initializations.
"""

from __future__ import annotations

import logging
from pathlib import Path

from lincona.config import LogLevel
from lincona.sessions import session_dir


def session_log_path(session_id: str, base_dir: Path | None = None) -> Path:
    directory = session_dir(session_id, base_dir)
    return directory / "log.txt"


def configure_session_logger(
    session_id: str,
    *,
    log_level: LogLevel | str = LogLevel.INFO,
    base_dir: Path | None = None,
) -> logging.Logger:
    """Configure and return a file logger scoped to a session.

    Subsequent calls with the same session_id return the same logger without
    duplicating handlers.
    """

    logger_name = f"lincona.session.{session_id}"
    logger = logging.getLogger(logger_name)

    level_value = _to_logging_level(log_level)
    logger.setLevel(level_value)
    logger.propagate = False

    if not logger.handlers:
        path = session_log_path(session_id, base_dir)
        path.parent.mkdir(parents=True, exist_ok=True)

        handler = logging.FileHandler(path, encoding="utf-8")
        handler.setLevel(level_value)
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        logger.addHandler(handler)

    return logger


def _to_logging_level(value: LogLevel | str) -> int:
    mapping = {
        LogLevel.DEBUG: logging.DEBUG,
        LogLevel.INFO: logging.INFO,
        LogLevel.WARNING: logging.WARNING,
        LogLevel.ERROR: logging.ERROR,
    }
    if isinstance(value, LogLevel):
        return mapping[value]
    if isinstance(value, str):
        try:
            return mapping[LogLevel(value)]
        except ValueError:
            return logging.WARNING
    return logging.WARNING


__all__ = [
    "configure_session_logger",
    "session_log_path",
    "_to_logging_level",
]
