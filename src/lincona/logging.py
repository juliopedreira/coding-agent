"""Logging setup for Lincona sessions.

Provides a per-session file logger with size-based truncation to guard against
unbounded growth. The logger is isolated (no propagation) and avoids duplicate
handlers across repeated initializations.
"""

from __future__ import annotations

import logging
import warnings
from pathlib import Path

from lincona.config import LogLevel
from lincona.paths import get_lincona_home

DEFAULT_MAX_BYTES = 5 * 1024 * 1024  # 5 MB


def session_log_path(session_id: str, base_dir: Path | None = None) -> Path:
    directory = base_dir or (get_lincona_home() / "logs")
    return directory / f"{session_id}.log"


def configure_session_logger(
    session_id: str,
    *,
    log_level: LogLevel | str = LogLevel.WARNING,
    base_dir: Path | None = None,
    max_bytes: int | None = DEFAULT_MAX_BYTES,
) -> logging.Logger:
    """Configure and return a file logger scoped to a session.

    Subsequent calls with the same session_id return the same logger without
    duplicating handlers. If the log file exceeds ``max_bytes``, it is
    truncated before attaching the handler.
    """

    logger_name = f"lincona.session.{session_id}"
    logger = logging.getLogger(logger_name)

    level_value = _to_logging_level(log_level)
    logger.setLevel(level_value)
    logger.propagate = False

    if not logger.handlers:
        path = session_log_path(session_id, base_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        _truncate_if_oversize(path, max_bytes)

        handler = logging.FileHandler(path, encoding="utf-8")
        handler.setLevel(level_value)
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        logger.addHandler(handler)

    return logger


def _truncate_if_oversize(path: Path, max_bytes: int | None) -> None:
    if max_bytes is None or max_bytes <= 0:
        return
    if not path.exists():
        return
    size = path.stat().st_size
    if size <= max_bytes:
        return
    data = path.read_bytes()
    path.write_bytes(data[-max_bytes:])


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
            warnings.warn(
                f"Unknown log level '{value}', defaulting to WARNING",
                RuntimeWarning,
                stacklevel=2,
            )
            return logging.WARNING
    return logging.WARNING


__all__ = [
    "configure_session_logger",
    "session_log_path",
    "DEFAULT_MAX_BYTES",
]
