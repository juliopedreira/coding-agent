"""Interactive REPL agent that streams OpenAI Responses and executes tools."""

from __future__ import annotations

import asyncio
import json
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from lincona.config import ApprovalPolicy, FsMode, Settings
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
            self.session_id, log_level=settings.log_level, base_dir=self._home / "logs"
        )
        shutdown_manager.register_logger(self.logger)

        self.router = ToolRouter(self.boundary, self.approval_policy, shutdown_manager=shutdown_manager)

        transport_instance = cast(
            ResponsesTransport, transport or OpenAISDKResponsesTransport(api_key=self._require_api_key())
        )
        self.client = OpenAIResponsesClient(
            transport_instance,
            default_model=settings.model,
            default_reasoning_effort=None,
        )

        self.history: list[Message] = []

    async def repl(self) -> None:
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
            self.history.extend(tool_messages)
            for msg in tool_messages:
                self._record_event(Role.TOOL, msg.content, tool_name=msg.tool_call_id)

        return assistant_text

    async def _invoke_model(self) -> tuple[str, list[_ToolCallBuffer]]:
        reasoning_effort = None
        if "mini" not in (self.settings.model or ""):
            reasoning_effort = self.settings.reasoning_effort

        request = ConversationRequest(
            messages=self.history,
            model=self.settings.model,
            reasoning_effort=reasoning_effort,
            tools=_tool_definitions(),
        )

        assistant_text_parts: list[str] = []
        tool_calls: list[_ToolCallBuffer] = []
        buffers: dict[str, str] = {}

        async for event in self.client.submit(request):
            if not self._handle_stream_event(event, assistant_text_parts, buffers, tool_calls):
                break

        return "".join(assistant_text_parts), tool_calls

    def _handle_stream_event(
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
            sys.stdout.write(event.text)
            sys.stdout.flush()
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
                sys.stdout.write("\n")
                sys.stdout.flush()
            return False

        if isinstance(event, ErrorEvent):  # pragma: no cover - defensive
            sys.stdout.write(f"\n[error] {event.error}\n")
            sys.stdout.flush()
            return False

        return True

    def _execute_tools(self, tool_calls: Iterable[_ToolCallBuffer]) -> list[Message]:
        messages: list[Message] = []
        for call in tool_calls:
            try:
                args = json.loads(call.arguments) if call.arguments else {}
                if not isinstance(args, dict):
                    raise ValueError("tool call arguments must decode to object")
            except Exception as exc:
                result = {"error": f"invalid tool args: {exc}"}
            else:
                try:
                    result = self.router.dispatch(call.tool_call.name, **args)
                except Exception as exc:  # pragma: no cover - tool errors surfaced to user
                    result = {"error": str(exc)}

            content = json.dumps(result)
            messages.append(
                Message(
                    role=MessageRole.TOOL,
                    content=content,
                    tool_call_id=call.tool_call.id,
                )
            )
        return messages

    async def _handle_slash(self, text: str) -> bool:
        parts = text.split()
        cmd = parts[0]
        if cmd == "/quit":
            print("bye")
            shutdown_manager.run()
            sys.exit(0)
        if cmd == "/help":
            print(
                "Commands: /newsession, /model <id>, /reasoning <low|medium|high>, "
                "/approvals <never|on-request|always>, /fsmode <restricted|unrestricted>, /quit"
            )
            return True
        if cmd == "/newsession":
            await self._rotate_session()
            print(f"Started new session {self.session_id}")
            return True
        if cmd == "/model" and len(parts) >= 2:
            self.settings = Settings(**{**self.settings.model_dump(), "model": " ".join(parts[1:])})
            print(f"model set to {self.settings.model}")
            return True
        if cmd == "/reasoning" and len(parts) >= 2:
            value = parts[1].lower()
            self.settings = Settings(**{**self.settings.model_dump(), "reasoning_effort": value})
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

    async def _rotate_session(self) -> None:
        try:
            self.writer.close()
        except Exception:
            pass
        self.session_id = generate_session_id()
        self.writer = JsonlEventWriter(session_path(self.session_id, self._home / "sessions"))
        shutdown_manager.register_event_writer(self.writer)
        self.logger = configure_session_logger(
            self.session_id, log_level=self.settings.log_level, base_dir=self._home / "logs"
        )
        shutdown_manager.register_logger(self.logger)
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

    @staticmethod
    def _uuid() -> Any:
        from uuid import uuid4

        return uuid4()

    @staticmethod
    def _now() -> Any:
        from datetime import UTC, datetime

        return datetime.now(UTC)

    def _require_api_key(self) -> str:
        key = self.settings.api_key
        if not key:
            raise SystemExit("OPENAI_API_KEY not set and api_key missing in config")
        return key


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
