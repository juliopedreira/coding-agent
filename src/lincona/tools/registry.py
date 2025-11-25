"""Shared tool registration structures.

Tools declare their own Pydantic input/output models and expose registrations
via ``tool_registrations`` in each module. ``ToolRouter`` consumes these to
build specs and handlers.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel


@dataclass(frozen=True)
class ToolRegistration:
    name: str
    description: str
    input_model: type[BaseModel]
    output_model: type[BaseModel]
    handler: Callable[[BaseModel], BaseModel]
    requires_approval: bool = False
    result_adapter: Callable[[BaseModel], Any] | None = None
    end_event_builder: Callable[[BaseModel, BaseModel], dict[str, Any]] | None = None


__all__ = ["ToolRegistration"]
