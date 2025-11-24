import asyncio
import io

import pytest

from lincona.config import ApprovalPolicy, FsMode, LogLevel, ReasoningEffort, Settings
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
    return Settings(
        api_key="test",
        model="gpt-4.1-mini",
        reasoning_effort=ReasoningEffort.LOW,
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
    assert messages[0].role is not None
    assert "invalid" in messages[0].content


def test_slash_commands_update_state(settings, monkeypatch, tmp_path):
    monkeypatch.setenv("LINCONA_HOME", str(tmp_path / "home"))
    transport = SequenceTransport([['data: {"type":"response.done"}']])
    runner = AgentRunner(settings, transport=transport, boundary_root=tmp_path)

    asyncio.run(runner._handle_slash("/model new-model"))
    assert runner.settings.model == "new-model"

    asyncio.run(runner._handle_slash("/reasoning high"))
    assert runner.settings.reasoning_effort.value == "high"

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
    assert any("x.txt" in m.content for m in msgs)
