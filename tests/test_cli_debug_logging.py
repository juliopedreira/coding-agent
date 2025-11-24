from pathlib import Path

from lincona.cli import main


def test_debug_flag_writes_log(tmp_path: Path, capsys) -> None:
    log_file = tmp_path / "dbg.log"

    rc = main(["--debug", str(log_file)])

    assert rc == 0
    assert log_file.exists()
    content = log_file.read_text()
    # should include filename and line marker
    assert "cli.py" in content
    assert ":" in content  # line number separator
