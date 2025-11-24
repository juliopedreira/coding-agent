"""Graceful shutdown management for Lincona.

Registers callbacks (event writers, loggers, PTY closers, etc.) and ensures
they are flushed/closed exactly once on SIGINT, SIGTERM, or interpreter exit.
"""

from __future__ import annotations

import atexit
import logging
import signal
from collections.abc import Callable, Iterable
from typing import Any

from lincona.sessions import JsonlEventWriter


class ShutdownManager:
    """Coordinate graceful shutdown callbacks."""

    def __init__(self, *, install_hooks: bool = True) -> None:
        self._callbacks: list[Callable[[], None]] = []
        self._pty_closers: list[Callable[[], None]] = []
        self._ran = False
        self._logger = logging.getLogger("lincona.shutdown")
        self._old_handlers: dict[int, Any] = {}
        self._restored = False
        if install_hooks:
            for sig in (signal.SIGINT, signal.SIGTERM):
                self._old_handlers[sig] = signal.getsignal(sig)
                signal.signal(sig, self._handle_signal)
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

    def register_pty_manager(self, manager: Any) -> None:
        """Register a PTY manager that exposes close_all()."""

        def _close() -> None:
            close_all = getattr(manager, "close_all", None)
            if callable(close_all):
                close_all()

        self.register(_close)

    def register_resources(
        self,
        *,
        writers: Iterable[JsonlEventWriter] | None = None,
        loggers: Iterable[logging.Logger] | None = None,
    ) -> None:
        if writers:
            for writer in writers:
                self.register_event_writer(writer)
        if loggers:
            for logger in loggers:
                self.register_logger(logger)

    def run(self) -> None:
        """Execute registered callbacks once (latest registered first)."""

        if self._ran:
            return
        self._ran = True

        for callback in reversed(self._callbacks):
            try:
                callback()
            except Exception:
                self._logger.exception("Shutdown callback failed")
                continue
        self._restore_signal_handlers()

    def _handle_signal(self, signum: int, frame: Any) -> None:  # pragma: no cover - thin wrapper
        self.run()

    def _restore_signal_handlers(self) -> None:
        if self._restored:
            return
        for sig, handler in self._old_handlers.items():
            signal.signal(sig, handler)
        self._restored = True


# Default global manager used by the application
shutdown_manager = ShutdownManager()


__all__ = ["ShutdownManager", "shutdown_manager"]
