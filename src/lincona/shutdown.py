"""Graceful shutdown management for Lincona.

Registers callbacks (event writers, loggers, PTY closers, etc.) and ensures
they are flushed/closed exactly once on SIGINT, SIGTERM, or interpreter exit.
"""

from __future__ import annotations

import atexit
import logging
import signal
from collections.abc import Callable
from typing import Any

from lincona.sessions import JsonlEventWriter


class ShutdownManager:
    """Coordinate graceful shutdown callbacks."""

    def __init__(self, *, install_hooks: bool = True) -> None:
        self._callbacks: list[Callable[[], None]] = []
        self._ran = False
        if install_hooks:
            signal.signal(signal.SIGINT, self._handle_signal)
            signal.signal(signal.SIGTERM, self._handle_signal)
            atexit.register(self.run)

    def register(self, callback: Callable[[], None]) -> None:
        """Register a generic callback executed on shutdown (LIFO order)."""

        self._callbacks.append(callback)

    def register_event_writer(self, writer: JsonlEventWriter) -> None:
        """Register a JSONL writer to be closed on shutdown."""

        self.register(writer.close)

    def register_logger(self, logger: logging.Logger) -> None:
        """Register a logger whose handlers will be flushed/closed on shutdown."""

        def _close_handlers() -> None:
            for handler in list(logger.handlers):
                try:
                    handler.flush()
                finally:
                    handler.close()
                logger.removeHandler(handler)

        self.register(_close_handlers)

    def run(self) -> None:
        """Execute registered callbacks once (latest registered first)."""

        if self._ran:
            return
        self._ran = True

        for callback in reversed(self._callbacks):
            try:
                callback()
            except Exception:
                # Swallow errors to allow remaining callbacks to run; logging can
                # be added later once a global logger exists.
                continue

    def _handle_signal(self, signum: int, frame: Any) -> None:  # pragma: no cover - thin wrapper
        self.run()


# Default global manager used by the application
shutdown_manager = ShutdownManager()


__all__ = ["ShutdownManager", "shutdown_manager"]
