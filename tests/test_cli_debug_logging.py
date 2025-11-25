from pathlib import Path

import lincona.cli as cli
from lincona.cli import main


def test_debug_flag_writes_log(tmp_path: Path, capsys, monkeypatch) -> None:
    monkeypatch.setenv("LINCONA_HOME", str(tmp_path))
    monkeypatch.setenv("OPENAI_API_KEY", "test")

    async def fake_repl(self):
        return None

    monkeypatch.setattr(cli.AgentRunner, "repl", fake_repl)

    rc = main(["--debug", str(tmp_path / "ignored.log"), "chat"])

    assert rc == 0
    sessions_root = tmp_path / "sessions"
    session_dirs = [p for p in sessions_root.iterdir() if p.is_dir()]
    assert len(session_dirs) == 1
    log_file = session_dirs[0] / "log.txt"
    assert log_file.exists()
    content = log_file.read_text()
    assert "session started" in content
