import argparse
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from lincona import __version__, cli
from lincona.config import ApprovalPolicy, FsMode, LogLevel, Settings


def test_version_constant() -> None:
    assert __version__ == "0.1.0"


def test_tool_subcommand_invokes_router(mock_tool_router_patch, mock_print) -> None:
    mock_tool_router_patch.set_dispatch_return({"ok": True})

    print_mock = mock_print

    settings = Settings(api_key="test", fs_mode=FsMode.RESTRICTED, approval_policy=ApprovalPolicy.NEVER)
    args = argparse.Namespace(name="list_dir", json_payload=None, arg=["path=.", "depth=1"], command="tool")
    code = cli._run_tool(settings, args)

    assert code == 0
    print_mock.assert_called_once()
    assert '"ok": true' in print_mock.call_args[0][0].lower()
    assert len(mock_tool_router_patch.dispatch_calls) == 1
    assert mock_tool_router_patch.dispatch_calls[0][0] == "list_dir"
    assert mock_tool_router_patch.dispatch_calls[0][1]["path"] == "."


def test_config_path(mock_lincona_home, mock_print) -> None:
    settings = Settings(api_key="test", fs_mode=FsMode.RESTRICTED, approval_policy=ApprovalPolicy.NEVER)
    args = argparse.Namespace(config_cmd="path")
    print_mock = mock_print

    code = cli._run_config(settings, args)

    assert code == 0
    print_mock.assert_called_once()
    assert str(print_mock.call_args[0][0]).endswith("config.toml")


def test_config_print(mock_lincona_home, mock_print) -> None:
    settings = Settings(
        api_key="test", model="demo-model", fs_mode=FsMode.RESTRICTED, approval_policy=ApprovalPolicy.NEVER
    )
    args = argparse.Namespace(config_cmd="print")
    print_mock = mock_print

    code = cli._run_config(settings, args)

    assert code == 0
    print_mock.assert_called_once()
    assert "demo-model" in print_mock.call_args[0][0]


@pytest.mark.asyncio
async def test_chat_runs_with_stub(mocker, no_session_io):
    called = {}

    async def fake_repl(self):
        called["ran"] = True

    mocker.patch.object(cli.AgentRunner, "repl", autospec=True, side_effect=fake_repl)

    await cli._run_chat(
        Settings(
            api_key="test",
            model="gpt-5.1-codex-mini",
            fs_mode=FsMode.RESTRICTED,
            approval_policy=ApprovalPolicy.NEVER,
        )
    )

    assert called["ran"] is True


def test_show_models_capabilities(mock_openai_patch, mock_print):
    mock_openai_patch(models_data=["gpt-5.1-codex-mini", "gpt-4o"])
    print_mock = mock_print

    settings = Settings(api_key="k", fs_mode=FsMode.RESTRICTED, approval_policy=ApprovalPolicy.NEVER)
    rc = cli._run_show_models_capabilities(settings)
    assert rc == 0
    print_mock.assert_called()
    output = " ".join(str(call[0][0]) for call in print_mock.call_args_list)
    assert "gpt-5.1-codex-mini" in output


def test_sessions_list_show_rm(mocker, mock_print):
    session_id = "202401010000-1234"
    fake_home = Path("/virtual/home")
    fake_session_path = fake_home / "sessions" / session_id / "events.jsonl"

    fake_list = [
        SimpleNamespace(session_id=session_id, modified_at=datetime(2024, 1, 1), size_bytes=12, path=fake_session_path)
    ]
    mocker.patch("lincona.cli.get_lincona_home", autospec=True, return_value=fake_home)
    mocker.patch("lincona.cli.list_sessions", autospec=True, return_value=fake_list)
    mocker.patch.object(Path, "exists", autospec=True, side_effect=lambda self: self == fake_session_path)
    mocker.patch.object(Path, "read_text", autospec=True, return_value='{"hello":true}')
    delete_mock = mocker.patch("lincona.cli.delete_session", autospec=True)
    print_mock = mock_print

    list_args = argparse.Namespace(sessions_cmd="list", session_id=None)
    show_args = argparse.Namespace(sessions_cmd="show", session_id=session_id)
    rm_args = argparse.Namespace(sessions_cmd="rm", session_id=session_id)

    assert cli._run_sessions(list_args) == 0
    assert session_id in print_mock.call_args_list[0][0][0]

    assert cli._run_sessions(show_args) == 0
    assert "hello" in print_mock.call_args_list[1][0][0]

    assert cli._run_sessions(rm_args) == 0
    delete_mock.assert_called_once_with(session_id, fake_home / "sessions")


def test_sessions_show_missing(mocker, mock_print):
    fake_home = Path("/virtual/home")
    mocker.patch("lincona.cli.get_lincona_home", autospec=True, return_value=fake_home)
    mocker.patch.object(Path, "exists", autospec=True, return_value=False)
    print_mock = mock_print
    args = argparse.Namespace(sessions_cmd="show", session_id="missing-session")

    rc = cli._run_sessions(args)

    assert rc == 1
    print_mock.assert_called_once()
    assert "not found" in print_mock.call_args[0][0]


def test_tool_arg_requires_equals():
    settings = Settings(api_key="test")
    args = argparse.Namespace(name="list_dir", json_payload=None, arg=["bad"], command="tool")
    with pytest.raises(SystemExit):
        cli._run_tool(settings, args)


def test_tool_json_payload(mock_tool_router_patch, mock_print):
    mock_tool_router_patch.set_dispatch_return({"ok": True})
    _ = mock_print  # ensure print is mocked

    settings = Settings(api_key="test")
    args = argparse.Namespace(name="list_dir", json_payload='{"path": "."}', arg=[], command="tool")
    rc = cli._run_tool(settings, args)
    assert rc == 0
    assert mock_tool_router_patch.dispatch_calls[0][1]["path"] == "."


def test_run_config_unknown_command():
    settings = Settings(api_key="test")
    args = argparse.Namespace(config_cmd="unknown")
    assert cli._run_config(settings, args) == 1


def test_main_unknown_command():
    with pytest.raises(SystemExit):
        cli.main(["unknown"])


def test_run_tool_dispatch_error(mock_tool_router_patch, mock_print):
    def raise_error(*args, **kwargs):
        raise RuntimeError("fail")

    mock_tool_router_patch.dispatch = raise_error  # type: ignore[assignment]
    _ = mock_print  # ensure print is mocked

    settings = Settings(api_key="test")
    args = argparse.Namespace(name="list_dir", json_payload=None, arg=[], command="tool")
    rc = cli._run_tool(settings, args)
    assert rc == 1


def test_sessions_unknown_command():
    args = argparse.Namespace(sessions_cmd="noop", session_id="x")
    assert cli._run_sessions(args) == 1


def test_show_models_requires_api_key(mocker, mock_print):
    settings = Settings(api_key=None)
    print_mock = mock_print
    rc = cli._run_show_models_capabilities(settings)
    assert rc == 1
    print_mock.assert_called()
    output = " ".join(str(call[0][0]) for call in print_mock.call_args_list)
    assert "OPENAI_API_KEY not set" in output


def test_show_models_handles_exception(mocker, bad_client_factory, mock_print):
    bad_client = bad_client_factory()
    mocker.patch("lincona.cli.OpenAI", autospec=True, return_value=bad_client)
    print_mock = mock_print
    settings = Settings(api_key="k", fs_mode=FsMode.RESTRICTED, approval_policy=ApprovalPolicy.NEVER)
    rc = cli._run_show_models_capabilities(settings)
    assert rc == 1
    print_mock.assert_called()
    output = " ".join(str(call[0][0]) for call in print_mock.call_args_list)
    assert "failed to fetch models" in output


def test_show_models_handles_no_rows(mock_openai_patch, mock_print):
    mock_openai_patch(models_data=["not-gpt"])
    print_mock = mock_print
    settings = Settings(api_key="k", fs_mode=FsMode.RESTRICTED, approval_policy=ApprovalPolicy.NEVER)
    rc = cli._run_show_models_capabilities(settings)
    assert rc == 0
    print_mock.assert_called()
    output = " ".join(str(call[0][0]) for call in print_mock.call_args_list)
    assert "no GPT-5 models" in output


def test_cli_main_entrypoint(mocker):
    import runpy
    import sys

    # ensure a clean import to avoid RuntimeWarning about existing module
    sys.modules.pop("lincona.cli", None)
    mocker.patch("sys.argv", ["lincona", "--version"])
    with pytest.raises(SystemExit):
        runpy.run_module("lincona.cli", run_name="__main__")


def test_main_handles_unknown_command_branch(mocker):
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

    mocker.patch.object(cli.argparse.ArgumentParser, "parse_args", autospec=True, side_effect=fake_parse_args)
    # avoid real repl execution
    mocker.patch("lincona.cli._run_chat", autospec=True, return_value=None)
    with pytest.raises(SystemExit):
        cli.main(["weird"])


def test_debug_flag_writes_log(tmp_path: Path) -> None:
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
