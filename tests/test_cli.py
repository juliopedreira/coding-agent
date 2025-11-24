from lincona import __version__, cli


def test_version_constant() -> None:
    assert __version__ == "0.1.0"


def test_tool_subcommand_invokes_router(monkeypatch, capsys) -> None:
    called = {}

    def fake_dispatch(self, name, **kwargs):
        called["name"] = name
        called["kwargs"] = kwargs
        return {"ok": True}

    monkeypatch.setattr(cli.ToolRouter, "dispatch", fake_dispatch)
    code = cli.main(["tool", "list_dir", "--arg", "path=.", "--arg", "depth=1"])
    assert code == 0
    out = capsys.readouterr().out
    assert '"ok": true' in out.lower()
    assert called["name"] == "list_dir"
    assert called["kwargs"]["path"] == "."


def test_config_path(monkeypatch, capsys, tmp_path) -> None:
    monkeypatch.setenv("LINCONA_HOME", str(tmp_path / "home"))
    code = cli.main(["config", "path"])
    assert code == 0
    out = capsys.readouterr().out.strip()
    assert out.endswith("config.toml")


def test_config_print(monkeypatch, capsys, tmp_path) -> None:
    monkeypatch.setenv("LINCONA_HOME", str(tmp_path / "home"))
    code = cli.main(["config", "print"])
    assert code == 0
    out = capsys.readouterr().out
    assert "model" in out


def test_chat_runs_with_stub(monkeypatch):
    called = {}

    async def fake_repl(self):
        called["ran"] = True

    monkeypatch.setattr(cli.AgentRunner, "repl", fake_repl)
    # Provide dummy api key to avoid SystemExit in AgentRunner creation
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    # Also stub AgentRunner __init__ to skip heavy setup
    original_init = cli.AgentRunner.__init__

    def fake_init(self, settings):  # type: ignore[override]
        called["init"] = settings.model
        return None

    monkeypatch.setattr(cli.AgentRunner, "__init__", fake_init)
    code = cli.main(["--model", "gpt-test", "chat"])
    assert code == 0
    assert called["init"] == "gpt-test"
    assert called["ran"] is True
    monkeypatch.setattr(cli.AgentRunner, "__init__", original_init)


def test_sessions_list_show_rm(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("LINCONA_HOME", str(tmp_path / "home"))
    sessions_dir = tmp_path / "home" / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    session_id = "202401010000-1234"
    session_file = sessions_dir / f"{session_id}.jsonl"
    session_file.write_text('{"hello":true}\n', encoding="utf-8")

    assert cli.main(["sessions", "list"]) == 0
    out = capsys.readouterr().out
    assert session_id in out

    assert cli.main(["sessions", "show", session_id]) == 0
    out = capsys.readouterr().out
    assert "hello" in out

    assert cli.main(["sessions", "rm", session_id]) == 0
    assert not session_file.exists()
