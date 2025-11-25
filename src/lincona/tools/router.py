"""Tool router exposing specs and dispatch for OpenAI tooling."""

from __future__ import annotations

import json
import logging
from typing import Any

from lincona.config import ApprovalPolicy
from lincona.tools.apply_patch import apply_patch
from lincona.tools.approval import ApprovalRequiredError, approval_guard
from lincona.tools.exec_pty import PtyManager
from lincona.tools.fs import FsBoundary
from lincona.tools.grep_files import grep_files
from lincona.tools.list_dir import list_dir
from lincona.tools.read_file import read_file
from lincona.tools.shell import run_shell


def tool_specs() -> list[dict[str, Any]]:
    """Return JSON tool specs matching MVP_00 parameters."""

    return [
        {
            "type": "function",
            "function": {
                "name": "list_dir",
                "description": "List directory entries up to depth",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "default": "."},
                        "depth": {"type": "integer", "default": 2, "minimum": 0},
                        "offset": {"type": "integer", "default": 0, "minimum": 0},
                        "limit": {"type": "integer", "default": 200, "minimum": 1},
                    },
                    "required": ["path", "depth", "offset", "limit"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "Read file slice with optional indentation mode",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "offset": {"type": "integer", "default": 0, "minimum": 0},
                        "limit": {"type": "integer", "default": 400, "minimum": 1},
                        "mode": {"type": "string", "enum": ["slice", "indentation"], "default": "slice"},
                        "indent": {"type": "string", "default": "    "},
                    },
                    "required": ["path", "offset", "limit", "mode", "indent"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "grep_files",
                "description": "Recursive regex search with include globs",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "pattern": {"type": "string"},
                        "path": {"type": "string", "default": "."},
                        "include": {"type": "array", "items": {"type": "string"}},
                        "limit": {"type": "integer", "default": 200, "minimum": 1},
                    },
                    "required": ["pattern", "path", "include", "limit"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "apply_patch_json",
                "description": "Apply unified diff",
                "parameters": {
                    "type": "object",
                    "properties": {"patch": {"type": "string"}},
                    "required": ["patch"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "apply_patch_freeform",
                "description": "Apply patch using freeform envelope",
                "parameters": {
                    "type": "object",
                    "properties": {"patch": {"type": "string"}},
                    "required": ["patch"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "shell",
                "description": "Run a shell command",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {"type": "string"},
                        "workdir": {"type": "string"},
                        "timeout_ms": {"type": "integer", "default": 60000, "minimum": 1},
                    },
                    "required": ["command", "workdir", "timeout_ms"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "exec_command",
                "description": "Run a PTY-backed long command",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "session_id": {"type": "string"},
                        "cmd": {"type": "string"},
                        "workdir": {"type": "string"},
                    },
                    "required": ["session_id", "cmd", "workdir"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "write_stdin",
                "description": "Send input to existing PTY session",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "session_id": {"type": "string"},
                        "chars": {"type": "string"},
                    },
                    "required": ["session_id", "chars"],
                    "additionalProperties": False,
                },
            },
        },
    ]


class ToolRouter:
    """Dispatch tool calls with boundary and approval enforcement."""

    def __init__(
        self,
        boundary: FsBoundary,
        approval_policy: ApprovalPolicy,
        pty_manager: PtyManager | None = None,
        shutdown_manager: Any | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self.boundary = boundary
        self.approval_policy = approval_policy
        self.pty_manager = pty_manager or PtyManager(boundary)
        self.logger = logger
        if shutdown_manager is not None:
            register = getattr(shutdown_manager, "register_pty_manager", None)
            if callable(register):
                register(self.pty_manager)
        self.events: list[dict[str, Any]] = []

    def dispatch(self, name: str, **kwargs: Any) -> Any:
        self._emit_event("start", name, kwargs)
        self._log_request(name, kwargs)
        result: Any
        try:
            if name == "list_dir":
                result = list_dir(self.boundary, **kwargs)
            elif name == "read_file":
                result = read_file(self.boundary, **kwargs)
            elif name == "grep_files":
                result = grep_files(self.boundary, **kwargs)
            elif name == "apply_patch_json":
                self._check_approval(name)
                result = apply_patch(self.boundary, kwargs["patch"])
                self._emit_event("end", name, {"files": len(result)})
            elif name == "apply_patch_freeform":
                self._check_approval(name)
                result = apply_patch(self.boundary, kwargs["patch"], freeform=True)
                self._emit_event("end", name, {"files": len(result)})
            elif name == "shell":
                self._check_approval(name)
                result = run_shell(self.boundary, **kwargs)
                self._emit_event(
                    "end", name, {"returncode": result.get("returncode"), "timeout": result.get("timeout")}
                )
            elif name == "exec_command":
                self._check_approval(name)
                result = self.pty_manager.exec_command(**kwargs)
                self._emit_event(
                    "end", name, {"session_id": kwargs.get("session_id"), "truncated": result.get("truncated")}
                )
            elif name == "write_stdin":
                self._check_approval(name)
                result = self.pty_manager.write_stdin(**kwargs)
                self._emit_event(
                    "end", name, {"session_id": kwargs.get("session_id"), "truncated": result.get("truncated")}
                )
            else:
                raise ValueError(f"unknown tool {name}")
        except Exception as exc:
            self._log_response(name, {"error": str(exc)})
            raise

        self._log_response(name, result)
        return result

    def _check_approval(self, tool_name: str) -> None:
        approval_guard(self.approval_policy, tool_name)

    def _emit_event(self, phase: str, tool_name: str, data: dict[str, Any]) -> None:
        self.events.append({"phase": phase, "tool": tool_name, **data})

    def _log_request(self, name: str, kwargs: dict[str, Any]) -> None:
        if not self.logger:
            return
        self.logger.info("tool request: %s args=%s", name, self._stringify(kwargs))

    def _log_response(self, name: str, result: Any) -> None:
        if not self.logger:
            return
        self.logger.debug("tool response: %s result=%s", name, self._stringify(result))

    @staticmethod
    def _stringify(obj: Any) -> str:
        try:
            text = json.dumps(obj, default=str)
        except Exception:
            text = repr(obj)

        if len(text) > 2000:
            return f"{text[:2000]}... [truncated]"
        return text


__all__ = ["tool_specs", "ToolRouter", "ApprovalRequiredError"]
