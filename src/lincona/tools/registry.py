"""Shared tool registration structures.

Tools declare their own Pydantic input/output models and expose registrations
via ``tool_registrations`` in each module. ``ToolRouter`` consumes these to
build specs and handlers.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from lincona.tools.base import ToolRequest, ToolResponse


@dataclass(frozen=True)
class ToolRegistration:
    name: str
    description: str
    input_model: type[ToolRequest]
    output_model: type[ToolResponse]
    handler: Callable[[ToolRequest], ToolResponse]
    requires_approval: bool = False
    result_adapter: Callable[[ToolResponse], Any] | None = None
    end_event_builder: Callable[[ToolRequest, ToolResponse], dict[str, Any]] | None = None


__all__ = ["ToolRegistration"]
