from pathlib import Path

import pytest

from lincona.config import ApprovalPolicy, FsMode, ModelCapabilities
from lincona.openai_client.types import (
    ErrorEvent,
    Message,
    MessageDone,
    MessageRole,
    TextDelta,
    ToolCallDelta,
    ToolCallEnd,
    ToolCallPayload,
    ToolCallStart,
)
from lincona.repl import AgentRunner, _json_default, _ToolCallBuffer
from lincona.tools.apply_patch import PatchResult
from lincona.tools.fs import FsBoundary
from lincona.tools.router import ToolRouter


@pytest.fixture()
def settings(default_settings):
    """Reuse default_settings fixture for REPL tests."""
    return default_settings


@pytest.mark.asyncio
async def test_run_turn_text_only(settings, mocker, tmp_path, no_session_io, sequence_transport, mock_lincona_home):
    transport = sequence_transport(
        [
            [
                'data: {"type":"text_delta","delta":{"text":"hi"}}',
                'data: {"type":"response.done"}',
            ]
        ]
    )
    runner = AgentRunner(settings, transport=transport, boundary_root=tmp_path)
    text = await runner.run_turn("hello")
    assert text == "hi"


@pytest.mark.asyncio
async def test_run_turn_tool_call(
    settings, mocker, tmp_path, no_session_io, fake_tool_router, sequence_transport, mock_lincona_home
):
    from tests.conftest import FakeToolRouter

    transport = sequence_transport(
        [
            [
                'data: {"type":"tool_call_start","delta":{"id":"tc1","name":"list_dir","arguments":""}}',
                ('data: {"type":"tool_call_delta","delta":{"id":"tc1","arguments_delta":' '"{\\"path\\": \\".\\"}"}}'),
                (
                    'data: {"type":"tool_call_end","delta":{"id":"tc1","name":"list_dir","arguments":'
                    '"{\\"path\\": \\".\\"}"}}'
                ),
                'data: {"type":"response.done"}',
            ],
            [
                'data: {"type":"text_delta","delta":{"text":"done"}}',
                'data: {"type":"response.done"}',
            ],
        ]
    )

    router_instance = FakeToolRouter()
    router_instance.set_dispatch_return({"ok": True})

    runner = AgentRunner(settings, transport=transport, boundary_root=tmp_path)
    runner.router = router_instance  # type: ignore[assignment]
    text = await runner.run_turn("use tool")
    assert '"ok": true' in text
    assert router_instance.dispatch_calls[0][0] == "list_dir"
    assert router_instance.dispatch_calls[0][1]["path"] == "."


def test_execute_tools_invalid_json(settings, tmp_path, sequence_transport):
    transport = sequence_transport(
        [
            [
                'data: {"type":"response.done"}',
            ]
        ]
    )
    runner = AgentRunner(settings, transport=transport, boundary_root=tmp_path)
    bad_call = _ToolCallBuffer(tool_call=ToolCallPayload(id="x", name="list_dir", arguments=""), arguments="not-json")
    messages = runner._execute_tools([bad_call])
    first_msg, _ = messages[0]
    assert first_msg.role is not None
    assert "invalid" in first_msg.content


@pytest.mark.asyncio
async def test_slash_commands_update_state(
    settings, mocker, tmp_path, no_session_io, success_transport, mock_lincona_home
):
    runner = AgentRunner(settings, transport=success_transport, boundary_root=tmp_path)

    await runner._handle_slash("/model:set gpt-5.1-codex-mini:minimal:low")
    assert runner.settings.model == "gpt-5.1-codex-mini"
    assert runner.settings.reasoning_effort.value == "minimal"
    assert runner.settings.verbosity.value == "low"

    await runner._handle_slash("/reasoning none")
    assert runner.settings.reasoning_effort.value == "none"

    # invalid reasoning for model
    await runner._handle_slash("/model:set gpt-5.1-codex-mini:unknown")
    assert runner.settings.reasoning_effort.value == "none"

    await runner._handle_slash("/approvals never")
    assert runner.approval_policy == ApprovalPolicy.NEVER

    await runner._handle_slash("/fsmode unrestricted")
    assert runner.fs_mode == FsMode.UNRESTRICTED


def test_execute_tools_serializes_patch_result(settings, tmp_path, success_transport, dataclass_router_factory):
    runner = AgentRunner(settings, transport=success_transport, boundary_root=tmp_path)

    # replace router dispatch to return a dataclass result
    router = dataclass_router_factory(PatchResult(path=tmp_path / "x.txt", bytes_written=4, created=True))
    runner.router = router  # type: ignore[assignment]
    msgs = runner._execute_tools(
        [_ToolCallBuffer(tool_call=ToolCallPayload(id="p1", name="apply_patch_json", arguments="{}"), arguments="{}")]
    )
    assert any("x.txt" in m.content for m, _ in msgs)


@pytest.mark.asyncio
async def test_model_commands_list_and_set_validation(
    settings, mocker, tmp_path, no_session_io, success_transport, mock_lincona_home, mock_print
):
    runner = AgentRunner(settings, transport=success_transport, boundary_root=tmp_path)

    print_mock = mock_print

    await runner._handle_slash("/model:list --json")
    output = " ".join(str(call[0][0]) for call in print_mock.call_args_list if call[0])
    assert "gpt-5.1-codex-mini" in output
    assert "reasoning_effort" in output

    print_mock.reset_mock()
    await runner._handle_slash("/model:set unknown-model")
    assert runner.settings.model == settings.model  # unchanged
    output = " ".join(str(call[0][0]) for call in print_mock.call_args_list if call[0])
    assert "not configured" in output


@pytest.mark.asyncio
async def test_model_set_rejects_unsupported_verbosity(
    settings, mocker, tmp_path, no_session_io, success_transport, mock_lincona_home, mock_print, settings_factory
):
    # remove verbosity support to force rejection
    stripped_models = {
        "gpt-5.1-codex-mini": ModelCapabilities(
            reasoning_effort=settings.models["gpt-5.1-codex-mini"].reasoning_effort,
            default_reasoning=settings.models["gpt-5.1-codex-mini"].default_reasoning,
            verbosity=(),
            default_verbosity=None,
        )
    }
    patched_settings = settings_factory(models=stripped_models)
    runner = AgentRunner(patched_settings, transport=success_transport, boundary_root=tmp_path)
    print_mock = mock_print

    await runner._handle_slash("/model:set gpt-5.1-codex-mini:none:low")
    output = " ".join(str(call[0][0]) for call in print_mock.call_args_list if call[0])
    assert "verbosity 'low' not supported" in output


def _stub_runner(settings, events, mocker, no_session_io, success_transport, dummy_client_factory):
    runner = AgentRunner(settings, transport=success_transport, boundary_root=Path("."))
    runner.client = dummy_client_factory(events)
    return runner


@pytest.mark.asyncio
async def test_handle_stream_event_variants(settings, mocker, no_session_io, success_transport, dummy_client_factory):
    events = [
        TextDelta(text="chunk"),
        ToolCallStart(tool_call=ToolCallPayload(id="c1", name="t", arguments="")),
        ToolCallDelta(tool_call_id="c1", arguments_delta="{}", name="t"),
        ToolCallEnd(tool_call=ToolCallPayload(id="c1", name="t", arguments="{}")),
        MessageDone(finish_reason=None),
    ]
    runner = _stub_runner(settings, events, mocker, no_session_io, success_transport, dummy_client_factory)
    runner.router = ToolRouter(FsBoundary(FsMode.UNRESTRICTED), ApprovalPolicy.NEVER)  # real router needed
    # ensure tool call execution returns non-empty output to exercise logging branch
    runner._execute_tools = lambda calls: [
        (Message(role=MessageRole.TOOL, content="tool-output", tool_call_id=calls[0].tool_call.id), calls[0])
    ]
    text = await runner.run_turn("go")
    assert text.startswith("chunk")
    assert "tool-output" in text


@pytest.mark.asyncio
async def test_handle_stream_error_branch(settings, mocker, no_session_io, sequence_transport, dummy_client_factory):
    err = ErrorEvent(error=RuntimeError("boom"))
    runner = _stub_runner(settings, [err], mocker, no_session_io, sequence_transport, dummy_client_factory)
    stdout_write_mock = mocker.patch("sys.stdout.write", autospec=True)
    await runner.run_turn("err")
    stdout_write_mock.assert_called()
    # Error is written to stdout via _safe_write, check that "boom" was written
    output = "".join(str(call[0][0]) for call in stdout_write_mock.call_args_list if call[0])
    assert "boom" in output or "RuntimeError" in output


def test_execute_tools_dispatch_failure(
    settings, mocker, no_session_io, sequence_transport, dummy_client_factory, failing_router_factory
):
    runner = _stub_runner(
        settings, [MessageDone(finish_reason=None)], mocker, no_session_io, sequence_transport, dummy_client_factory
    )

    router = failing_router_factory(error_message="bad")
    runner.router = router  # type: ignore[assignment]
    buf = _ToolCallBuffer(tool_call=ToolCallPayload(id="x", name="noop", arguments="{}"), arguments="{}")
    messages = runner._execute_tools([buf])
    assert "bad" in messages[0][0].content


@pytest.mark.asyncio
async def test_slash_usage_and_invalid_reasoning(
    settings, mocker, no_session_io, sequence_transport, mock_print, dummy_client_factory
):
    runner = _stub_runner(
        settings, [MessageDone(finish_reason=None)], mocker, no_session_io, sequence_transport, dummy_client_factory
    )
    print_mock = mock_print
    await runner._handle_slash("/model:set")
    await runner._handle_slash("/reasoning nope")
    output = " ".join(str(call[0][0]) for call in print_mock.call_args_list if call[0])
    assert "usage: /model:set" in output
    assert "reasoning must be one of" in output


def test_print_model_list_text_path(
    settings, mocker, no_session_io, sequence_transport, mock_print, dummy_client_factory
):
    runner = _stub_runner(
        settings, [MessageDone(finish_reason=None)], mocker, no_session_io, sequence_transport, dummy_client_factory
    )
    print_mock = mock_print
    runner._print_model_list()
    output = " ".join(str(call[0][0]) for call in print_mock.call_args_list if call[0])
    assert "Available models" in output


def test_set_model_missing_defaults(
    mocker, settings, no_session_io, success_transport, mock_print, dummy_client_factory, settings_factory
):
    caps = ModelCapabilities(reasoning_effort=(), default_reasoning=None, verbosity=(), default_verbosity=None)
    settings = settings_factory(models={"empty": caps}, model="empty")
    runner = _stub_runner(
        settings, [MessageDone(finish_reason=None)], mocker, no_session_io, success_transport, dummy_client_factory
    )
    print_mock = mock_print
    runner._set_model("empty")
    output = " ".join(str(call[0][0]) for call in print_mock.call_args_list if call[0])
    assert "no default reasoning" in output


def test_require_api_key_raises(settings, success_transport, settings_factory):
    no_key = settings_factory(api_key=None)
    runner = AgentRunner(no_key, transport=success_transport)
    with pytest.raises(SystemExit):
        runner._require_api_key()


def test_json_default_handles_bytes_and_path(tmp_path):
    class Demo:
        def __init__(self, p):
            self.path = p

    assert _json_default(b"abc") == "abc"
    assert str(tmp_path / "x") == _json_default(tmp_path / "x")
    # dataclass coverage is already handled elsewhere; ensure str fallback
    assert "Demo" in _json_default(Demo(tmp_path / "y"))
