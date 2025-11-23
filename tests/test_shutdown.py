import logging
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest

from lincona.sessions import Event, JsonlEventWriter, Role
from lincona.shutdown import ShutdownManager


def _sample_writer(tmp_path: Path) -> JsonlEventWriter:
    return JsonlEventWriter(tmp_path / "session.jsonl")


def _sample_event() -> Event:
    return Event(
        timestamp=datetime(2025, 1, 2, 3, 4, 5, tzinfo=UTC),
        event_type="message",
        id=UUID("12345678-1234-5678-1234-567812345678"),
        trace_id=None,
        role=Role.USER,
        content="hi",
        metadata={},
        error=None,
        tool_name=None,
    )


def test_callbacks_run_once_in_reverse_order():
    mgr = ShutdownManager(install_hooks=False)
    calls: list[str] = []

    mgr.register(lambda: calls.append("first"))
    mgr.register(lambda: calls.append("second"))

    mgr.run()
    mgr.run()

    assert calls == ["second", "first"]


def test_exceptions_do_not_block_others():
    mgr = ShutdownManager(install_hooks=False)
    calls: list[str] = []

    def boom():
        raise RuntimeError("boom")

    mgr.register(boom)
    mgr.register(lambda: calls.append("ok"))

    mgr.run()

    assert calls == ["ok"]


def test_register_event_writer_closes(tmp_path: Path):
    writer = _sample_writer(tmp_path)
    writer.append(_sample_event())

    mgr = ShutdownManager(install_hooks=False)
    mgr.register_event_writer(writer)

    mgr.run()

    assert writer._closed is True  # type: ignore[attr-defined]


def test_register_logger_closes_handlers(tmp_path: Path):
    mgr = ShutdownManager(install_hooks=False)
    logger = logging.getLogger("test.shutdown")
    logger.setLevel(logging.INFO)
    handler = logging.FileHandler(tmp_path / "log.log")
    logger.addHandler(handler)

    mgr.register_logger(logger)
    mgr.run()

    assert logger.handlers == []
    assert handler.stream is None


def test_signal_handler_triggers_run(monkeypatch: pytest.MonkeyPatch):
    mgr = ShutdownManager(install_hooks=False)
    flag = SimpleNamespace(count=0)
    mgr.register(lambda: setattr(flag, "count", flag.count + 1))

    mgr._handle_signal(2, None)

    assert flag.count == 1


def test_register_resources_combines(tmp_path: Path):
    writer = _sample_writer(tmp_path)
    logger = logging.getLogger("test.shutdown.resources")
    handler = logging.FileHandler(tmp_path / "log.log")
    logger.addHandler(handler)

    mgr = ShutdownManager(install_hooks=False)
    mgr.register_resources(writers=[writer], loggers=[logger])
    mgr.run()

    assert writer._closed is True  # type: ignore[attr-defined]
    assert logger.handlers == []
