"""Tool router exposing specs and dispatch for OpenAI tooling.

All tool parameters and outputs are defined via Pydantic models in
per-tool modules. Tool specs advertised to the model are generated directly
from each tool's Pydantic input schema to keep definitions DRY and typed.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any

from lincona.config import ApprovalPolicy, FsMode
from lincona.tools import get_tool_registrations
from lincona.tools.approval import ApprovalRequiredError, approval_guard
from lincona.tools.base import ToolRequest, ToolResponse
from lincona.tools.exec_pty import PtyManager
from lincona.tools.fs import FsBoundary


def tool_specs(boundary: FsBoundary | None = None, pty_manager: PtyManager | None = None) -> list[dict[str, Any]]:
    """Return OpenAI tool specs derived from Pydantic schemas."""

    effective_boundary = boundary or FsBoundary(FsMode.RESTRICTED)
    effective_pty = pty_manager or PtyManager(effective_boundary)
    regs = get_tool_registrations(effective_boundary, effective_pty)
    specs: list[dict[str, Any]] = []
    for reg in regs:
        params = reg.input_model.model_json_schema()
        if isinstance(params, dict):
            params.setdefault("additionalProperties", False)
        specs.append(
            {
                "type": "function",
                "function": {
                    "name": reg.name,
                    "description": reg.description,
                    "parameters": params,
                },
            }
        )
    return specs


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
        self._registrations = get_tool_registrations(self.boundary, self.pty_manager)
        self._spec_index = {reg.name: reg for reg in self._registrations}
        self._handlers: dict[str, Callable[[ToolRequest], ToolResponse]] = self._build_handlers()

    def dispatch(self, name: str, **kwargs: Any) -> Any:
        spec = self._spec_index.get(name)
        handler = self._handlers.get(name)
        if spec is None or handler is None:
            raise ValueError(f"unknown tool {name}")

        self._emit_event("start", name, kwargs)
        self._log_request(name, kwargs)

        try:
            validated = spec.input_model.model_validate(kwargs)
            if spec.requires_approval:
                self._check_approval(name)
            output_model = handler(validated)
            result = spec.result_adapter(output_model) if spec.result_adapter else output_model.model_dump()
        except Exception as exc:
            self._log_response(name, {"error": str(exc)})
            raise

        end_builder = spec.end_event_builder
        end_data = end_builder(validated, output_model) if end_builder else {}
        self._emit_event("end", name, end_data)
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

    def _build_handlers(self) -> dict[str, Callable[[ToolRequest], ToolResponse]]:
        handlers: dict[str, Callable[[ToolRequest], ToolResponse]] = {}
        for reg in self._registrations:
            handlers[reg.name] = reg.handler
        return handlers


__all__ = ["tool_specs", "ToolRouter", "ApprovalRequiredError"]
