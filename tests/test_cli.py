import argparse
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from lincona import __version__, cli
from lincona.config import FsMode, LogLevel


def test_version_constant() -> None:
    assert __version__ == "0.1.0"


def test_tool_subcommand_invokes_router(mock_tool_router_patch, mock_print, restricted_settings) -> None:
    mock_tool_router_patch.set_dispatch_return({"ok": True})

    print_mock = mock_print

    args = argparse.Namespace(name="list_dir", json_payload=None, arg=["path=.", "depth=1"], command="tool")
    code = cli._run_tool(restricted_settings, args)

    assert code == 0
    print_mock.assert_called_once()
    assert '"ok": true' in print_mock.call_args[0][0].lower()
    assert len(mock_tool_router_patch.dispatch_calls) == 1
    assert mock_tool_router_patch.dispatch_calls[0][0] == "list_dir"
    assert mock_tool_router_patch.dispatch_calls[0][1]["path"] == "."


def test_config_path(mock_lincona_home, mock_print, restricted_settings) -> None:
    args = argparse.Namespace(config_cmd="path")
    print_mock = mock_print

    code = cli._run_config(restricted_settings, args)

    assert code == 0
    print_mock.assert_called_once()
    assert str(print_mock.call_args[0][0]).endswith("config.toml")


def test_config_print(mock_lincona_home, mock_print, settings_factory) -> None:
    settings = settings_factory(model="demo-model", fs_mode=FsMode.RESTRICTED)
    args = argparse.Namespace(config_cmd="print")
    print_mock = mock_print

    code = cli._run_config(settings, args)

    assert code == 0
    print_mock.assert_called_once()
    assert "demo-model" in print_mock.call_args[0][0]


@pytest.mark.asyncio
async def test_chat_runs_with_stub(mock_agent_runner_repl, no_session_io, restricted_settings):
    called = {}

    async def fake_repl(self):
        called["ran"] = True

    mock_agent_runner_repl(side_effect=fake_repl)

    await cli._run_chat(restricted_settings)

    assert called["ran"] is True


def test_show_models_capabilities(mock_openai_patch, mock_print, restricted_settings):
    mock_openai_patch(models_data=["gpt-5.1-codex-mini", "gpt-4o"])
    print_mock = mock_print

    rc = cli._run_show_models_capabilities(restricted_settings)
    assert rc == 0
    print_mock.assert_called()
    output = " ".join(str(call[0][0]) for call in print_mock.call_args_list)
    assert "gpt-5.1-codex-mini" in output


def test_sessions_list_show_rm(mock_delete_session, mock_print, mock_cli_path_methods, mock_sessions_fixture):
    session_id = "202401010000-1234"
    fake_home = Path("/virtual/home")
    fake_session_path = fake_home / "sessions" / session_id / "events.jsonl"

    fake_list = [
        SimpleNamespace(session_id=session_id, modified_at=datetime(2024, 1, 1), size_bytes=12, path=fake_session_path)
    ]
    delete_mock = mock_delete_session()
    mock_sessions_fixture(home=fake_home, sessions=fake_list)
    mock_cli_path_methods(
        exists=lambda self: self == fake_session_path,
        read_text='{"hello":true}',
    )
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


def test_sessions_show_missing(mocker, mock_print, mock_cli_path_methods, mock_sessions_fixture):
    fake_home = Path("/virtual/home")
    mock_sessions_fixture(home=fake_home)
    mock_cli_path_methods(exists=False)
    print_mock = mock_print
    args = argparse.Namespace(sessions_cmd="show", session_id="missing-session")

    rc = cli._run_sessions(args)

    assert rc == 1
    print_mock.assert_called_once()
    assert "not found" in print_mock.call_args[0][0]


def test_tool_arg_requires_equals(settings_factory):
    settings = settings_factory(api_key="test")
    args = argparse.Namespace(name="list_dir", json_payload=None, arg=["bad"], command="tool")
    with pytest.raises(SystemExit):
        cli._run_tool(settings, args)


def test_tool_json_payload(mock_tool_router_patch, mock_print, settings_factory):
    mock_tool_router_patch.set_dispatch_return({"ok": True})
    _ = mock_print  # ensure print is mocked

    settings = settings_factory(api_key="test")
    args = argparse.Namespace(name="list_dir", json_payload='{"path": "."}', arg=[], command="tool")
    rc = cli._run_tool(settings, args)
    assert rc == 0
    assert mock_tool_router_patch.dispatch_calls[0][1]["path"] == "."


def test_run_config_unknown_command(settings_factory):
    settings = settings_factory(api_key="test")
    args = argparse.Namespace(config_cmd="unknown")
    assert cli._run_config(settings, args) == 1


def test_main_unknown_command():
    with pytest.raises(SystemExit):
        cli.main(["unknown"])


def test_run_tool_dispatch_error(mock_tool_router_patch, mock_print, settings_factory):
    def raise_error(*args, **kwargs):
        raise RuntimeError("fail")

    mock_tool_router_patch.dispatch = raise_error  # type: ignore[assignment]
    _ = mock_print  # ensure print is mocked

    settings = settings_factory(api_key="test")
    args = argparse.Namespace(name="list_dir", json_payload=None, arg=[], command="tool")
    rc = cli._run_tool(settings, args)
    assert rc == 1


def test_sessions_unknown_command():
    args = argparse.Namespace(sessions_cmd="noop", session_id="x")
    assert cli._run_sessions(args) == 1


def test_show_models_requires_api_key(mocker, mock_print, settings_factory):
    settings = settings_factory(api_key=None)
    print_mock = mock_print
    rc = cli._run_show_models_capabilities(settings)
    assert rc == 1
    print_mock.assert_called()
    output = " ".join(str(call[0][0]) for call in print_mock.call_args_list)
    assert "OPENAI_API_KEY not set" in output


def test_show_models_handles_exception(mock_openai_client_patch, bad_client_factory, mock_print, restricted_settings):
    bad_client = bad_client_factory()
    mock_openai_client_patch(client=bad_client)
    print_mock = mock_print
    rc = cli._run_show_models_capabilities(restricted_settings)
    assert rc == 1
    print_mock.assert_called()
    output = " ".join(str(call[0][0]) for call in print_mock.call_args_list)
    assert "failed to fetch models" in output


def test_show_models_handles_no_rows(mock_openai_patch, mock_print, restricted_settings):
    mock_openai_patch(models_data=["not-gpt"])
    print_mock = mock_print
    rc = cli._run_show_models_capabilities(restricted_settings)
    assert rc == 0
    print_mock.assert_called()
    output = " ".join(str(call[0][0]) for call in print_mock.call_args_list)
    assert "no GPT-5 models" in output


def test_cli_main_entrypoint(mock_sys_argv):
    import runpy
    import sys

    # ensure a clean import to avoid RuntimeWarning about existing module
    sys.modules.pop("lincona.cli", None)
    mock_sys_argv(["lincona", "--version"])
    with pytest.raises(SystemExit):
        runpy.run_module("lincona.cli", run_name="__main__")


def test_main_handles_unknown_command_branch(mock_argparse_parse_args, mock_run_chat):
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

    mock_argparse_parse_args(side_effect=fake_parse_args)
    # avoid real repl execution
    mock_run_chat(return_value=None)
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
