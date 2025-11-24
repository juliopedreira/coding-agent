from pathlib import Path

import lincona.cli as cli
from lincona.cli import main


def test_debug_flag_writes_log(tmp_path: Path, capsys, monkeypatch) -> None:
    log_file = tmp_path / "dbg.log"

    async def fake_repl(self):
        return None

    def fake_init(self, settings):  # type: ignore[override]
        return None

    monkeypatch.setattr(cli.AgentRunner, "__init__", fake_init)
    monkeypatch.setattr(cli.AgentRunner, "repl", fake_repl)

    rc = main(["--debug", str(log_file), "chat"])

    assert rc == 0
    assert log_file.exists()
    content = log_file.read_text()
    # should include filename and line marker
    assert "cli.py" in content
    assert ":" in content  # line number separator
