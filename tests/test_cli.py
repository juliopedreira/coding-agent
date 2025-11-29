import argparse
import asyncio
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from lincona import __version__, cli
from lincona.config import ApprovalPolicy, FsMode, LogLevel, Settings


def test_version_constant() -> None:
    assert __version__ == "0.1.0"


def test_tool_subcommand_invokes_router(monkeypatch) -> None:
    called = {}

    class DummyRouter:
        def dispatch(self, name, **kwargs):
            called["name"] = name
            called["kwargs"] = kwargs
            return {"ok": True}

    monkeypatch.setattr(cli, "ToolRouter", lambda boundary, approval_policy: DummyRouter())
    settings = Settings(api_key="test", fs_mode=FsMode.RESTRICTED, approval_policy=ApprovalPolicy.NEVER)
    args = argparse.Namespace(name="list_dir", json_payload=None, arg=["path=.", "depth=1"], command="tool")
    printed: list[str] = []
    monkeypatch.setattr("builtins.print", lambda *a, **k: printed.append(" ".join(str(x) for x in a)))

    code = cli._run_tool(settings, args)

    assert code == 0
    assert '"ok": true' in printed[0].lower()
    assert called["name"] == "list_dir"
    assert called["kwargs"]["path"] == "."


def test_config_path(monkeypatch, capsys, tmp_path) -> None:
    monkeypatch.setenv("LINCONA_HOME", str(tmp_path / "home"))
    settings = Settings(api_key="test", fs_mode=FsMode.RESTRICTED, approval_policy=ApprovalPolicy.NEVER)
    args = argparse.Namespace(config_cmd="path")
    printed: list[str] = []
    monkeypatch.setattr("builtins.print", lambda *a, **k: printed.append(str(a[0])))

    code = cli._run_config(settings, args)

    assert code == 0
    assert printed[0].endswith("config.toml")


def test_config_print(monkeypatch, capsys, tmp_path) -> None:
    monkeypatch.setenv("LINCONA_HOME", str(tmp_path / "home"))
    settings = Settings(api_key="test", model="demo-model", fs_mode=FsMode.RESTRICTED, approval_policy=ApprovalPolicy.NEVER)
    args = argparse.Namespace(config_cmd="print")
    printed: list[str] = []
    monkeypatch.setattr("builtins.print", lambda *a, **k: printed.append(a[0]))

    code = cli._run_config(settings, args)

    assert code == 0
    assert "demo-model" in printed[0]


def test_chat_runs_with_stub(monkeypatch):
    called = {}

    async def fake_repl(self):
        called["ran"] = True

    monkeypatch.setattr(cli.AgentRunner, "repl", fake_repl)

    def fake_init(self, settings):
        called["init"] = settings.model
        return None

    monkeypatch.setattr(cli.AgentRunner, "__init__", fake_init)

    asyncio.run(cli._run_chat(Settings(api_key="test", model="gpt-5.1-codex-mini", fs_mode=FsMode.RESTRICTED, approval_policy=ApprovalPolicy.NEVER)))

    assert called["init"] == "gpt-5.1-codex-mini"
    assert called["ran"] is True


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

    monkeypatch.setattr(cli, "OpenAI", FakeClient)
    settings = Settings(api_key="k", fs_mode=FsMode.RESTRICTED, approval_policy=ApprovalPolicy.NEVER)
    rc = cli._run_show_models_capabilities(settings)
    assert rc == 0
    out = capsys.readouterr().out
    assert "gpt-5.1-codex-mini" in out


def test_sessions_list_show_rm(monkeypatch):
    session_id = "202401010000-1234"
    fake_home = Path("/virtual/home")
    fake_session_path = fake_home / "sessions" / session_id / "events.jsonl"

    monkeypatch.setattr(cli, "get_lincona_home", lambda: fake_home)
    fake_list = [
        SimpleNamespace(session_id=session_id, modified_at=datetime(2024, 1, 1), size_bytes=12, path=fake_session_path)
    ]
    monkeypatch.setattr(cli, "list_sessions", lambda path: fake_list)
    monkeypatch.setattr(Path, "exists", lambda self: self == fake_session_path, raising=False)
    monkeypatch.setattr(Path, "read_text", lambda self, encoding="utf-8": '{"hello":true}')
    deleted = {}
    monkeypatch.setattr(cli, "delete_session", lambda sid, root: deleted.setdefault("sid", sid))

    printed: list[str] = []
    monkeypatch.setattr("builtins.print", lambda *a, **k: printed.append(" ".join(str(x) for x in a)))

    list_args = argparse.Namespace(sessions_cmd="list", session_id=None)
    show_args = argparse.Namespace(sessions_cmd="show", session_id=session_id)
    rm_args = argparse.Namespace(sessions_cmd="rm", session_id=session_id)

    assert cli._run_sessions(list_args) == 0
    assert session_id in printed[0]

    assert cli._run_sessions(show_args) == 0
    assert "hello" in printed[1]

    assert cli._run_sessions(rm_args) == 0
    assert deleted["sid"] == session_id


def test_sessions_show_missing(monkeypatch, capsys, tmp_path):
    fake_home = Path("/virtual/home")
    monkeypatch.setattr(cli, "get_lincona_home", lambda: fake_home)
    monkeypatch.setattr(Path, "exists", lambda self: False, raising=False)
    printed_err: list[str] = []
    monkeypatch.setattr("builtins.print", lambda *a, **k: printed_err.append(a[0]))
    args = argparse.Namespace(sessions_cmd="show", session_id="missing-session")

    rc = cli._run_sessions(args)

    assert rc == 1
    assert "not found" in printed_err[0]


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
    args = argparse.Namespace(
        model=None,
        reasoning=None,
        verbosity=None,
        fs_mode=None,
        approval_policy=None,
        log_level=None,
    )
    overrides = cli._collect_overrides(args, debug_enabled=True)
    assert overrides["log_level"] == LogLevel.DEBUG.value
