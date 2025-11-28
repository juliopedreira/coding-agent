# pragma: no cover
"""Interactive REPL agent that streams OpenAI Responses and executes tools."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from collections.abc import Iterable
from dataclasses import asdict, dataclass, is_dataclass
from pathlib import Path
from typing import Any, cast

from lincona.config import ApprovalPolicy, FsMode, ReasoningEffort, Settings, Verbosity
from lincona.logging import configure_session_logger
from lincona.openai_client import OpenAIResponsesClient
from lincona.openai_client.transport import OpenAISDKResponsesTransport, ResponsesTransport
from lincona.openai_client.types import (
    ApplyPatchFreeform,
    ConversationRequest,
    Message,
    MessageRole,
    ResponseEvent,
    ToolCallPayload,
    ToolDefinition,
)
from lincona.paths import get_lincona_home
from lincona.sessions import Event, JsonlEventWriter, Role, generate_session_id, session_path
from lincona.shutdown import shutdown_manager
from lincona.tools.fs import FsBoundary
from lincona.tools.router import ToolRouter, tool_specs


@dataclass
class _ToolCallBuffer:
    tool_call: ToolCallPayload
    arguments: str


class AgentRunner:
    """Minimal REPL-style agent that can call tools via OpenAI Responses."""

    def __init__(
        self,
        settings: Settings,
        *,
        transport: ResponsesTransport | None = None,
        boundary_root: Path | None = None,
    ) -> None:
        self.settings = settings
        self.fs_mode = settings.fs_mode
        self.approval_policy = settings.approval_policy
        self.boundary = FsBoundary(self.fs_mode, boundary_root)
        self.session_id = generate_session_id()
        self._home = get_lincona_home()

        self.writer = JsonlEventWriter(session_path(self.session_id, self._home / "sessions"))
        shutdown_manager.register_event_writer(self.writer)

        self.logger = configure_session_logger(
            self.session_id, log_level=settings.log_level, base_dir=self._home / "sessions"
        )
        shutdown_manager.register_logger(self.logger)
        self.logger.info("session started: %s", self.session_id)

        self.router = ToolRouter(
            self.boundary, self.approval_policy, shutdown_manager=shutdown_manager, logger=self.logger
        )

        transport_instance = cast(
            ResponsesTransport, transport or OpenAISDKResponsesTransport(api_key=self._require_api_key())
        )
        self.client = OpenAIResponsesClient(
            transport_instance,
            default_model=settings.model,
            default_reasoning_effort=None,
        )

        self.history: list[Message] = [
            Message(
                role=MessageRole.SYSTEM,
                content=(
                    "You are Lincona, a coding agent. Always use the provided tools to inspect the repository "
                    "before answering questions about files, documentation, or code structure. The project source "
                    "lives under the current working directory (not empty). Prefer list_dir/read_file/grep_files "
                    "to gather evidence; do not guess."
                ),
            )
        ]

    async def repl(self) -> None:  # pragma: no cover - interactive loop
        """Run a synchronous-feeling REPL over asyncio."""

        print(f"Session: {self.session_id} | model={self.settings.model} fs_mode={self.fs_mode.value}")
        while True:
            try:
                user_text = await asyncio.to_thread(input, "> ")
            except EOFError:
                break
            if not user_text.strip():
                continue
            if user_text.startswith("/"):
                if await self._handle_slash(user_text.strip()):
                    continue
                # fallthrough when slash not recognized
            await self.run_turn(user_text)

    async def run_turn(self, user_text: str) -> str:
        """Send one user turn, execute tool calls, and stream assistant reply."""

        self._record_event(Role.USER, user_text)
        self.history.append(Message(role=MessageRole.USER, content=user_text))

        assistant_text: str = ""
        while True:
            assistant_chunk, tool_calls = await self._invoke_model()
            assistant_text += assistant_chunk
            if assistant_chunk:
                self.history.append(Message(role=MessageRole.ASSISTANT, content=assistant_chunk))
                self._record_event(Role.ASSISTANT, assistant_chunk)

            if not tool_calls:
                break

            tool_messages = self._execute_tools(tool_calls)
            self.history.extend(msg for msg, _ in tool_messages)
            for msg, call in tool_messages:
                self._record_event(Role.TOOL, msg.content, tool_name=call.tool_call.name)

            # Present tool outputs directly and feed them back to the model as user context.
            tool_text = self._format_tool_outputs([msg for msg, _ in tool_messages])
            if tool_text:  # pragma: no cover - presentation side-effect
                assistant_text += tool_text
                # Tool responses are logged instead of printed to the console.
                if self.logger:  # pragma: no cover - debug logging branch
                    self.logger.debug("tool output: %s", tool_text)
            for msg, call in tool_messages:
                feedback = f"Tool {call.tool_call.name} output:\n{msg.content}"
                feedback_msg = Message(role=MessageRole.USER, content=feedback)
                self.history.append(feedback_msg)
                self._record_event(Role.USER, feedback, tool_name=call.tool_call.name)
            # loop continues to ask the model again with new context

        return assistant_text

    async def _invoke_model(self) -> tuple[str, list[_ToolCallBuffer]]:  # pragma: no cover - network/stream
        request = ConversationRequest(
            messages=self.history,
            model=self.settings.model,
            reasoning_effort=None,
            tools=_tool_definitions(),
        )

        assistant_text_parts: list[str] = []
        tool_calls: list[_ToolCallBuffer] = []
        buffers: dict[str, str] = {}

        async for event in self.client.submit(request):
            if not self._handle_stream_event(event, assistant_text_parts, buffers, tool_calls):
                break

        return "".join(assistant_text_parts), tool_calls

    def _handle_stream_event(  # pragma: no cover - stream parsing exercised in integration
        self,
        event: ResponseEvent,
        text_parts: list[str],
        buffers: dict[str, str],
        tool_calls: list[_ToolCallBuffer],
    ) -> bool:
        from lincona.openai_client.types import (
            ErrorEvent,
            MessageDone,
            TextDelta,
            ToolCallDelta,
            ToolCallEnd,
            ToolCallStart,
        )

        if isinstance(event, TextDelta):
            self._safe_write(event.text)
            text_parts.append(event.text)
            return True

        if isinstance(event, ToolCallStart):
            buffers[event.tool_call.id] = event.tool_call.arguments or ""
            return True

        if isinstance(event, ToolCallDelta):
            buffers[event.tool_call_id] = buffers.get(event.tool_call_id, "") + event.arguments_delta
            return True

        if isinstance(event, ToolCallEnd):
            args = buffers.get(event.tool_call.id, "")
            tool_calls.append(_ToolCallBuffer(event.tool_call, args))
            return True

        if isinstance(event, MessageDone):
            if text_parts:
                self._safe_write("\n")
            return False

        if isinstance(event, ErrorEvent):  # pragma: no cover - defensive
            cause = getattr(event.error, "__cause__", None)
            self._safe_write(f"\n[error] {event.error!r} cause={cause!r}\n")
            return False

        return True

    def _execute_tools(self, tool_calls: Iterable[_ToolCallBuffer]) -> list[tuple[Message, _ToolCallBuffer]]:
        messages: list[tuple[Message, _ToolCallBuffer]] = []
        for call in tool_calls:
            try:
                args = json.loads(call.arguments) if call.arguments else {}
                if not isinstance(args, dict):  # pragma: no cover - defensive
                    raise ValueError("tool call arguments must decode to object")
            except Exception as exc:
                result = {"error": f"invalid tool args: {exc}"}
            else:
                try:
                    result = self.router.dispatch(call.tool_call.name, **args)
                except Exception as exc:  # pragma: no cover - tool errors surfaced to user
                    result = {"error": str(exc)}

            content = json.dumps(result, default=_json_default)
            messages.append(
                (
                    Message(
                        role=MessageRole.TOOL,
                        content=content,
                        tool_call_id=call.tool_call.id,
                    ),
                    call,
                )
            )
        return messages

    async def _handle_slash(self, text: str) -> bool:
        parts = text.split()
        cmd = parts[0]
        if cmd == "/quit":  # pragma: no cover - interactive exit
            print("bye")
            shutdown_manager.run()
            sys.exit(0)
        if cmd == "/help":  # pragma: no cover - interactive help
            print(
                "Commands: /newsession, /model:list, /model:set <id[:reasoning[:verbosity]]>, "
                "/reasoning <none|minimal|low|medium|high>, "
                "/approvals <never|on-request|always>, /fsmode <restricted|unrestricted>, /quit"
            )
            return True
        if cmd == "/newsession":  # pragma: no cover - interactive session rotation
            await self._rotate_session()
            print(f"Started new session {self.session_id}")
            return True
        if cmd in ("/model:list", "/modellist"):
            self._print_model_list()
            return True
        if cmd in ("/model:set", "/model"):
            if len(parts) < 2:
                print("usage: /model:set <model[:reasoning[:verbosity]]>")  # pragma: no cover - usage branch
                return True
            self._set_model(" ".join(parts[1:]))
            return True
        if cmd == "/reasoning" and len(parts) >= 2:
            value = parts[1].lower()
            if value not in {e.value for e in ReasoningEffort}:
                allowed = ", ".join(e.value for e in ReasoningEffort)
                print(f"reasoning must be one of: {allowed}")  # pragma: no cover - usage branch
                return True
            self.settings = Settings(**{**self.settings.model_dump(), "reasoning_effort": value})
            if self.settings.reasoning_effort is None:  # pragma: no cover - defensive
                return True
            print(f"reasoning set to {self.settings.reasoning_effort.value}")
            return True
        if cmd == "/approvals" and len(parts) >= 2:
            value = parts[1].lower()
            self.approval_policy = ApprovalPolicy(value)
            self.router.approval_policy = self.approval_policy
            print(f"approval policy set to {self.approval_policy.value}")
            return True
        if cmd == "/fsmode" and len(parts) >= 2:
            value = FsMode(parts[1].lower())
            self.fs_mode = value
            self.boundary = FsBoundary(self.fs_mode)
            self.router.boundary = self.boundary
            print(f"fs_mode set to {self.fs_mode.value}")
            return True
        return False

    async def _rotate_session(self) -> None:  # pragma: no cover - session rotation interactive
        try:
            self.writer.close()
        except Exception:
            pass
        self.session_id = generate_session_id()
        self.writer = JsonlEventWriter(session_path(self.session_id, self._home / "sessions"))
        shutdown_manager.register_event_writer(self.writer)
        self.logger = configure_session_logger(
            self.session_id, log_level=self.settings.log_level, base_dir=self._home / "sessions"
        )
        shutdown_manager.register_logger(self.logger)
        # Keep router logging in sync with the active session logger.
        self.router.logger = self.logger
        self.logger.info("session started: %s", self.session_id)
        self.history.clear()

    def _record_event(self, role: Role, content: Any, *, tool_name: str | None = None) -> None:
        event = Event(
            timestamp=self._now(),
            event_type="message",
            id=self._uuid(),
            role=role,
            content=content,
            tool_name=tool_name,
        )
        self.writer.append(event)

    def _print_model_list(self) -> None:
        print("Available models:")
        for model_id, cap in self.settings.models.items():
            marker = "*" if model_id == self.settings.model else " "
            reasoning_list = ",".join(v.value for v in cap.reasoning_effort) or "-"
            verbosity_list = ",".join(v.value for v in cap.verbosity) or "-"
            default_reason = cap.default_reasoning.value if cap.default_reasoning else "-"
            default_verb = cap.default_verbosity.value if cap.default_verbosity else "-"
            print(
                f"{marker} {model_id}  reasoning=[{reasoning_list}] default={default_reason} "
                f"verbosity=[{verbosity_list}] default={default_verb}"
            )

    def _set_model(self, token: str) -> None:
        parts = token.split(":")
        model_id = parts[0]
        reasoning_val = parts[1] if len(parts) >= 2 and parts[1] else None
        verbosity_val = parts[2] if len(parts) >= 3 and parts[2] else None

        if model_id not in self.settings.models:
            print(f"model '{model_id}' is not configured; add [models.{model_id}] to config")
            return
        cap = self.settings.models[model_id]

        reasoning_enum: ReasoningEffort | None = None
        if reasoning_val:
            try:
                reasoning_enum = ReasoningEffort(reasoning_val)
            except Exception:
                print(f"reasoning '{reasoning_val}' is invalid")  # pragma: no cover - validation branch
                return
            if reasoning_enum not in cap.reasoning_effort:
                print(f"reasoning '{reasoning_enum.value}' not supported for {model_id}")  # pragma: no cover
                return
        else:
            reasoning_enum = cap.default_reasoning
        if reasoning_enum is None:
            print(f"model '{model_id}' has no default reasoning configured")  # pragma: no cover
            return
        assert isinstance(reasoning_enum, ReasoningEffort)
        reasoning_final: ReasoningEffort = reasoning_enum

        verbosity_enum: Verbosity | None = None
        if verbosity_val:
            try:
                verbosity_enum = Verbosity(verbosity_val)
            except Exception:
                print(f"verbosity '{verbosity_val}' is invalid")  # pragma: no cover
                return
            if verbosity_enum not in cap.verbosity:
                print(f"verbosity '{verbosity_enum.value}' not supported for {model_id}")  # pragma: no cover
                return
        else:
            verbosity_enum = cap.default_verbosity
        if verbosity_enum is None:
            print(f"model '{model_id}' has no default verbosity configured")  # pragma: no cover
            return
        assert isinstance(verbosity_enum, Verbosity)
        verbosity_final: Verbosity = verbosity_enum

        self.settings = Settings(
            **{
                **self.settings.model_dump(),
                "model": model_id,
                "reasoning_effort": reasoning_final,
                "verbosity": verbosity_final,
            }
        )
        print(
            f"model set to {self.settings.model} "
            f"(reasoning={self.settings.reasoning_effort.value if self.settings.reasoning_effort else '-'}, "
            f"verbosity={self.settings.verbosity.value if self.settings.verbosity else '-'})"
        )

    @staticmethod
    def _format_tool_outputs(messages: list[Message]) -> str:
        parts = []
        for msg in messages:
            parts.append(msg.content)
        return "\n".join(parts)

    @staticmethod
    def _uuid() -> Any:  # pragma: no cover - simple wrapper
        from uuid import uuid4

        return uuid4()

    @staticmethod
    def _now() -> Any:  # pragma: no cover - simple wrapper
        from datetime import UTC, datetime

        return datetime.now(UTC)

    def _require_api_key(self) -> str:  # pragma: no cover - guard
        key = self.settings.api_key
        if not key:
            raise SystemExit("OPENAI_API_KEY not set and api_key missing in config")
        return key

    @staticmethod
    def _safe_write(text: str) -> None:  # pragma: no cover - IO guard
        try:
            sys.stdout.write(text)
            sys.stdout.flush()
        except BrokenPipeError:
            # Gracefully exit when stdout consumer closes (e.g., piped/timeout).
            os._exit(0)


def _json_default(obj: Any) -> Any:
    """Best-effort conversion for dataclasses/Path/etc. used in tool outputs."""

    if is_dataclass(obj) and not isinstance(obj, type):
        return {k: _json_default(v) for k, v in asdict(obj).items()}
    if isinstance(obj, Path):
        return str(obj)
    if isinstance(obj, bytes):
        return obj.decode(errors="ignore")
    return str(obj)


def _tool_definitions() -> list[ToolDefinition | ApplyPatchFreeform]:
    tools: list[ToolDefinition | ApplyPatchFreeform] = []
    for spec in tool_specs():
        func = spec["function"]
        tools.append(
            ToolDefinition(
                name=func["name"],
                description=func.get("description", ""),
                parameters=func.get("parameters", {}),
            )
        )
    tools.append(ApplyPatchFreeform())
    return tools


__all__ = ["AgentRunner"]
