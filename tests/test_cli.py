import argparse
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from lincona import __version__, cli
from lincona.config import ApprovalPolicy, FsMode, LogLevel, Settings


def test_version_constant() -> None:
    assert __version__ == "0.1.0"


def test_tool_subcommand_invokes_router(monkeypatch, capsys) -> None:
    called = {}

    def fake_dispatch(self, name, **kwargs):
        called["name"] = name
        called["kwargs"] = kwargs
        return {"ok": True}

    monkeypatch.setattr(cli.ToolRouter, "dispatch", fake_dispatch)
    monkeypatch.setattr(
        cli,
        "load_settings",
        lambda cli_overrides=None, config_path=None, create_if_missing=True: Settings(
            api_key="test", fs_mode=FsMode.RESTRICTED, approval_policy=ApprovalPolicy.NEVER
        ),
    )
    monkeypatch.setattr(cli, "_configure_base_logging", lambda debug_enabled=False, lincona_level=None: None)

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
    code = cli.main(["--model", "gpt-5.1-codex-mini", "chat"])
    assert code == 0
    assert called["init"] == "gpt-5.1-codex-mini"
    assert called["ran"] is True
    monkeypatch.setattr(cli.AgentRunner, "__init__", original_init)


def test_show_models_capabilities(monkeypatch, capsys):
    class FakeModel:
        def __init__(self, id):
            self.id = id

    class FakeModels:
        def list(self):
            class Obj:
                data = [FakeModel("gpt-5.1-codex-mini"), FakeModel("gpt-4o")]

            return Obj()

    class FakeClient:
        def __init__(self, api_key=None):
            self.models = FakeModels()

    monkeypatch.setenv("OPENAI_API_KEY", "k")
    monkeypatch.setattr(cli, "OpenAI", FakeClient)
    rc = cli.main(["--show-models-capabilities"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "gpt-5.1-codex-mini" in out


def test_sessions_list_show_rm(monkeypatch, capsys):
    session_id = "202401010000-1234"
    fake_home = Path("/virtual/home")
    fake_session_path = fake_home / "sessions" / session_id / "events.jsonl"

    monkeypatch.setattr(
        cli,
        "load_settings",
        lambda cli_overrides=None, config_path=None, create_if_missing=True: Settings(
            api_key="test", fs_mode=FsMode.RESTRICTED, approval_policy=ApprovalPolicy.NEVER
        ),
    )
    monkeypatch.setattr(cli, "_configure_base_logging", lambda debug_enabled=False, lincona_level=None: None)
    monkeypatch.setattr(cli, "get_lincona_home", lambda: fake_home)

    fake_list = [
        SimpleNamespace(session_id=session_id, modified_at=datetime(2024, 1, 1), size_bytes=12, path=fake_session_path)
    ]
    monkeypatch.setattr(cli, "list_sessions", lambda path: fake_list)
    monkeypatch.setattr(Path, "exists", lambda self: self == fake_session_path, raising=False)
    monkeypatch.setattr(Path, "read_text", lambda self, encoding="utf-8": '{"hello":true}')
    deleted = {}
    monkeypatch.setattr(cli, "delete_session", lambda sid, root: deleted.setdefault("sid", sid))

    assert cli.main(["sessions", "list"]) == 0
    out = capsys.readouterr().out
    assert session_id in out

    assert cli.main(["sessions", "show", session_id]) == 0
    out = capsys.readouterr().out
    assert "hello" in out

    assert cli.main(["sessions", "rm", session_id]) == 0
    assert deleted["sid"] == session_id


def test_sessions_show_missing(monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("LINCONA_HOME", str(tmp_path / "home"))
    rc = cli.main(["sessions", "show", "missing-session"])
    err = capsys.readouterr().err
    assert rc == 1
    assert "not found" in err


def test_tool_arg_requires_equals():
    settings = Settings(api_key="test")
    args = argparse.Namespace(name="list_dir", json_payload=None, arg=["bad"], command="tool")
    with pytest.raises(SystemExit):
        cli._run_tool(settings, args)


def test_tool_json_payload(monkeypatch):
    called = {}

    def fake_dispatch(self, name, **kwargs):
        called["payload"] = kwargs
        return {"ok": True}

    monkeypatch.setattr(cli.ToolRouter, "dispatch", fake_dispatch)

    settings = Settings(api_key="test")
    args = argparse.Namespace(name="list_dir", json_payload='{"path": "."}', arg=[], command="tool")
    rc = cli._run_tool(settings, args)
    assert rc == 0
    assert called["payload"]["path"] == "."


def test_run_config_unknown_command():
    settings = Settings(api_key="test")
    args = argparse.Namespace(config_cmd="unknown")
    assert cli._run_config(settings, args) == 1


def test_main_unknown_command(monkeypatch):
    with pytest.raises(SystemExit):
        cli.main(["unknown"])


def test_run_tool_dispatch_error(monkeypatch):
    settings = Settings(api_key="test")
    args = argparse.Namespace(name="list_dir", json_payload=None, arg=[], command="tool")
    monkeypatch.setattr(cli.ToolRouter, "dispatch", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("fail")))
    rc = cli._run_tool(settings, args)
    assert rc == 1


def test_sessions_unknown_command(monkeypatch):
    args = argparse.Namespace(sessions_cmd="noop", session_id="x")
    assert cli._run_sessions(args) == 1


def test_show_models_requires_api_key(monkeypatch, capsys):
    settings = Settings(api_key=None)
    rc = cli._run_show_models_capabilities(settings)
    assert rc == 1
    assert "OPENAI_API_KEY not set" in capsys.readouterr().err


def test_show_models_handles_exception(monkeypatch, capsys):
    class BadClient:
        class models:
            @staticmethod
            def list():
                raise RuntimeError("oops")

    monkeypatch.setattr(cli, "OpenAI", lambda api_key=None: BadClient)
    settings = Settings(api_key="k")
    rc = cli._run_show_models_capabilities(settings)
    assert rc == 1
    assert "failed to fetch models" in capsys.readouterr().err


def test_show_models_handles_no_rows(monkeypatch, capsys):
    class ModelObj:
        def __init__(self, id):
            self.id = id

    class FakeModels:
        def list(self):
            class Obj:
                data = [ModelObj("not-gpt")]

            return Obj()

    monkeypatch.setattr(cli, "OpenAI", lambda api_key=None: type("C", (), {"models": FakeModels()})())
    settings = Settings(api_key="k")
    rc = cli._run_show_models_capabilities(settings)
    assert rc == 0
    assert "no GPT-5 models" in capsys.readouterr().out


def test_cli_main_entrypoint(monkeypatch):
    import runpy
    import sys

    # ensure a clean import to avoid RuntimeWarning about existing module
    sys.modules.pop("lincona.cli", None)
    monkeypatch.setattr("sys.argv", ["lincona", "--version"])
    with pytest.raises(SystemExit):
        runpy.run_module("lincona.cli", run_name="__main__")


def test_main_handles_unknown_command_branch(monkeypatch):
    def fake_parse_args(self, argv=None):
        return argparse.Namespace(
            command="weird",
            debug=None,
            model=None,
            reasoning=None,
            verbosity=None,
            fs_mode=None,
            approval_policy=None,
            log_level=None,
            show_models_capabilities=False,
            config_path=None,
            json_payload=None,
            arg=[],
            sessions_cmd=None,
            config_cmd=None,
            name=None,
        )

    monkeypatch.setattr(cli.argparse.ArgumentParser, "parse_args", fake_parse_args, raising=False)
    # avoid real repl execution
    monkeypatch.setattr(cli, "_run_chat", lambda settings: None)
    with pytest.raises(SystemExit):
        cli.main(["weird"])


def test_debug_flag_writes_log(tmp_path: Path, capsys, monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test")

    captured_overrides: dict | None = None

    def fake_load_settings(cli_overrides=None, config_path=None, create_if_missing=True):
        nonlocal captured_overrides
        captured_overrides = cli_overrides
        return Settings(
            api_key="test", fs_mode=FsMode.RESTRICTED, approval_policy=ApprovalPolicy.NEVER, log_level=LogLevel.INFO
        )

    async def fake_repl(self):
        return None

    monkeypatch.setattr(cli, "load_settings", fake_load_settings)
    monkeypatch.setattr(cli, "_configure_base_logging", lambda debug_enabled=False, lincona_level=None: None)
    monkeypatch.setattr(cli.AgentRunner, "__init__", lambda self, settings: None)
    monkeypatch.setattr(cli.AgentRunner, "repl", fake_repl)

    rc = cli.main(["--debug", str(tmp_path / "ignored.log"), "chat"])

    assert rc == 0
    assert captured_overrides is not None
    assert captured_overrides["log_level"] == LogLevel.DEBUG
