import asyncio
import io

import pytest

from lincona.config import ApprovalPolicy, FsMode, LogLevel, ModelCapabilities, ReasoningEffort, Settings, Verbosity
from lincona.openai_client.types import ToolCallPayload
from lincona.repl import AgentRunner, _ToolCallBuffer
from lincona.tools.apply_patch import PatchResult
from lincona.tools.router import ToolRouter


class SequenceTransport:
    """Yield predefined chunk sequences per stream_response call."""

    def __init__(self, sequences):
        self.sequences = list(sequences)

    async def stream_response(self, payload):  # type: ignore[override]
        if not self.sequences:
            raise RuntimeError("no more streams")
        stream = self.sequences.pop(0)

        async def gen():
            for chunk in stream:
                yield chunk

        return gen()


@pytest.fixture()
def settings():
    models = {
        "gpt-5.1-codex-mini": ModelCapabilities(
            reasoning_effort=(
                ReasoningEffort.NONE,
                ReasoningEffort.MINIMAL,
                ReasoningEffort.LOW,
                ReasoningEffort.MEDIUM,
                ReasoningEffort.HIGH,
            ),
            default_reasoning=ReasoningEffort.MINIMAL,
            verbosity=(
                Verbosity.LOW,
                Verbosity.MEDIUM,
                Verbosity.HIGH,
            ),
            default_verbosity=Verbosity.MEDIUM,
        )
    }
    return Settings(
        api_key="test",
        model="gpt-5.1-codex-mini",
        reasoning_effort=ReasoningEffort.MINIMAL,
        verbosity=Verbosity.MEDIUM,
        models=models,
        fs_mode=FsMode.UNRESTRICTED,
        approval_policy=ApprovalPolicy.NEVER,
        log_level=LogLevel.ERROR,
    )


def test_run_turn_text_only(settings, monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("LINCONA_HOME", str(tmp_path / "home"))
    transport = SequenceTransport(
        [
            [
                'data: {"type":"text_delta","delta":{"text":"hi"}}',
                'data: {"type":"response.done"}',
            ]
        ]
    )
    runner = AgentRunner(settings, transport=transport, boundary_root=tmp_path)
    out = io.StringIO()
    monkeypatch.setattr("sys.stdout", out)
    text = asyncio.run(runner.run_turn("hello"))
    assert text == "hi"
    assert "hi" in out.getvalue()


def test_run_turn_tool_call(settings, monkeypatch, tmp_path):
    monkeypatch.setenv("LINCONA_HOME", str(tmp_path / "home"))
    transport = SequenceTransport(
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

    calls = {}

    class StubRouter(ToolRouter):
        def __init__(self):
            pass

        def dispatch(self, name: str, **kwargs):
            calls["name"] = name
            calls["kwargs"] = kwargs
            return {"ok": True}

    runner = AgentRunner(settings, transport=transport, boundary_root=tmp_path)
    runner.router = StubRouter()  # type: ignore[assignment]
    text = asyncio.run(runner.run_turn("use tool"))
    assert '"ok": true' in text
    assert calls["name"] == "list_dir"
    assert calls["kwargs"]["path"] == "."


def test_execute_tools_invalid_json(settings, tmp_path):
    transport = SequenceTransport(
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


def test_slash_commands_update_state(settings, monkeypatch, tmp_path):
    monkeypatch.setenv("LINCONA_HOME", str(tmp_path / "home"))
    transport = SequenceTransport([['data: {"type":"response.done"}']])
    runner = AgentRunner(settings, transport=transport, boundary_root=tmp_path)

    asyncio.run(runner._handle_slash("/model:set gpt-5.1-codex-mini:minimal:low"))
    assert runner.settings.model == "gpt-5.1-codex-mini"
    assert runner.settings.reasoning_effort.value == "minimal"
    assert runner.settings.verbosity.value == "low"

    asyncio.run(runner._handle_slash("/reasoning none"))
    assert runner.settings.reasoning_effort.value == "none"

    # invalid reasoning for model
    asyncio.run(runner._handle_slash("/model:set gpt-5.1-codex-mini:unknown"))
    assert runner.settings.reasoning_effort.value == "none"

    asyncio.run(runner._handle_slash("/approvals never"))
    assert runner.approval_policy == ApprovalPolicy.NEVER

    asyncio.run(runner._handle_slash("/fsmode unrestricted"))
    assert runner.fs_mode == FsMode.UNRESTRICTED


def test_execute_tools_serializes_patch_result(settings, tmp_path):
    transport = SequenceTransport(
        [
            [
                'data: {"type":"response.done"}',
            ]
        ]
    )
    runner = AgentRunner(settings, transport=transport, boundary_root=tmp_path)

    # replace router dispatch to return a dataclass result
    class DataclassRouter:
        def dispatch(self, name: str, **kwargs):
            return PatchResult(path=tmp_path / "x.txt", bytes_written=4, created=True)

    runner.router = DataclassRouter()  # type: ignore[assignment]
    msgs = runner._execute_tools(
        [_ToolCallBuffer(tool_call=ToolCallPayload(id="p1", name="apply_patch_json", arguments="{}"), arguments="{}")]
    )
    assert any("x.txt" in m.content for m, _ in msgs)


def test_model_commands_list_and_set_validation(settings, monkeypatch, tmp_path):
    monkeypatch.setenv("LINCONA_HOME", str(tmp_path / "home"))
    transport = SequenceTransport([['data: {"type":"response.done"}']])
    runner = AgentRunner(settings, transport=transport, boundary_root=tmp_path)

    buffer = io.StringIO()
    monkeypatch.setattr("sys.stdout", buffer)

    asyncio.run(runner._handle_slash("/model:list --json"))
    output = buffer.getvalue()
    assert "gpt-5.1-codex-mini" in output
    assert "reasoning_effort" in output

    buffer.truncate(0)
    buffer.seek(0)
    asyncio.run(runner._handle_slash("/model:set unknown-model"))
    assert runner.settings.model == settings.model  # unchanged
    assert "not configured" in buffer.getvalue()


def test_model_set_rejects_unsupported_verbosity(settings, monkeypatch, tmp_path):
    # remove verbosity support to force rejection
    stripped_models = {
        "gpt-5.1-codex-mini": ModelCapabilities(
            reasoning_effort=settings.models["gpt-5.1-codex-mini"].reasoning_effort,
            default_reasoning=settings.models["gpt-5.1-codex-mini"].default_reasoning,
            verbosity=(),
            default_verbosity=None,
        )
    }
    patched_settings = Settings(**{**settings.model_dump(), "models": stripped_models})
    monkeypatch.setenv("LINCONA_HOME", str(tmp_path / "home"))
    transport = SequenceTransport([['data: {"type":"response.done"}']])
    runner = AgentRunner(patched_settings, transport=transport, boundary_root=tmp_path)
    out = io.StringIO()
    monkeypatch.setattr("sys.stdout", out)

    asyncio.run(runner._handle_slash("/model:set gpt-5.1-codex-mini:none:low"))
    assert "verbosity 'low' not supported" in out.getvalue()
