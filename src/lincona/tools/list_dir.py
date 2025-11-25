"""Directory listing tool respecting filesystem boundaries."""

from __future__ import annotations

from collections import deque
from collections.abc import Callable
from pathlib import Path
from typing import cast

from pydantic import BaseModel, Field

from lincona.tools.base import Tool, ToolRequest, ToolResponse
from lincona.tools.fs import FsBoundary
from lincona.tools.registry import ToolRegistration


class ListDirInput(ToolRequest):
    path: str = Field(default=".", description="Root directory to list from.")
    depth: int = Field(default=2, ge=0, description="Maximum depth to traverse (BFS).")
    offset: int = Field(default=0, ge=0, description="Number of entries to skip from the start.")
    limit: int = Field(default=200, ge=1, description="Maximum number of entries to return.")


class ListDirOutput(ToolResponse):
    entries: list[str] = Field(description="Directory entries with markers (/ for dir, @ for symlink).")


class ListDirTool(Tool[ListDirInput, ListDirOutput]):
    name = "list_dir"
    description = "List directory entries up to depth"
    InputModel = ListDirInput
    OutputModel = ListDirOutput

    def __init__(self, boundary: FsBoundary) -> None:
        self.boundary = boundary

    def execute(self, request: ListDirInput) -> ListDirOutput:
        entries = list_dir(self.boundary, **request.model_dump())
        return ListDirOutput(entries=entries)


def list_dir(
    boundary: FsBoundary,
    path: str | Path = ".",
    *,
    depth: int = 2,
    offset: int = 0,
    limit: int = 200,
) -> list[str]:
    """Breadth-first directory listing up to a depth."""

    root = boundary.sanitize_path(path)
    boundary.assert_within_root(root)

    entries: list[str] = []
    queue: deque[tuple[Path, int]] = deque([(root, 0)])

    while queue and len(entries) < offset + limit:
        current, level = queue.popleft()
        try:
            children = sorted(current.iterdir(), key=lambda p: p.name.lower())
        except FileNotFoundError:
            break
        except NotADirectoryError:
            break

        for child in children:
            marker = "/"
            if child.is_file():
                marker = ""
            elif child.is_symlink():
                marker = "@"

            relative = child.relative_to(root)
            entry = f"{relative}{marker}"
            entries.append(entry)

            if level + 1 < depth and child.is_dir():
                queue.append((child, level + 1))

    return entries[offset : offset + limit]


def tool_registrations(boundary: FsBoundary) -> list[ToolRegistration]:
    tool = ListDirTool(boundary)

    def _end_event(validated: BaseModel, output: BaseModel) -> dict[str, object]:
        out = cast(ListDirOutput, output)
        return {"count": len(out.entries)}

    return [
        ToolRegistration(
            name="list_dir",
            description="List directory entries up to depth",
            input_model=ListDirInput,
            output_model=ListDirOutput,
            handler=cast(Callable[[ToolRequest], ToolResponse], tool.execute),
            result_adapter=lambda out: cast(ListDirOutput, out).entries,
            end_event_builder=_end_event,
        )
    ]


__all__ = [
    "list_dir",
    "tool_registrations",
    "ListDirInput",
    "ListDirOutput",
]
