"""Abstract base classes for tools."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import ClassVar, Generic, TypeVar

from pydantic import BaseModel

Req = TypeVar("Req", bound=BaseModel)
Res = TypeVar("Res", bound=BaseModel)


class ToolRequest(BaseModel):
    """Marker base class for tool requests."""


class ToolResponse(BaseModel):
    """Marker base class for tool responses."""


class Tool(Generic[Req, Res], ABC):
    """Abstract tool with typed request/response."""

    name: ClassVar[str]
    description: ClassVar[str]
    InputModel: ClassVar[type[Req]]
    OutputModel: ClassVar[type[Res]]
    requires_approval: ClassVar[bool] = False

    @abstractmethod
    def execute(self, request: Req) -> Res:
        """Run the tool and return a response."""


__all__ = ["ToolRequest", "ToolResponse", "Tool", "Req", "Res"]
