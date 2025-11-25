"""File reading tool with slicing and indentation modes."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import cast

from pydantic import BaseModel, Field

from lincona.tools.base import Tool, ToolRequest, ToolResponse
from lincona.tools.fs import FsBoundary
from lincona.tools.registry import ToolRegistration


class ReadFileInput(ToolRequest):
    path: str = Field(description="File path to read.")
    offset: int = Field(default=0, ge=0, description="Starting line (0-indexed).")
    limit: int = Field(default=400, ge=1, description="Maximum number of lines to return.")
    mode: str = Field(default="slice", description="Either 'slice' or 'indentation'.")
    indent: str = Field(default="    ", description="Indentation prefix when mode='indentation'.")


class ReadFileOutput(ToolResponse):
    text: str = Field(description="File contents (possibly truncated).")
    truncated: bool = Field(description="True when not all lines were returned.")


class ReadFileTool(Tool[ReadFileInput, ReadFileOutput]):
    name = "read_file"
    description = "Read file slice with optional indentation mode"
    InputModel = ReadFileInput
    OutputModel = ReadFileOutput

    def __init__(self, boundary: FsBoundary) -> None:
        self.boundary = boundary

    def execute(self, request: ReadFileInput) -> ReadFileOutput:
        text, truncated = read_file(self.boundary, **request.model_dump())
        return ReadFileOutput(text=text, truncated=truncated)


def read_file(
    boundary: FsBoundary,
    path: str | Path,
    *,
    offset: int = 0,
    limit: int = 400,
    mode: str = "slice",
    indent: str = "    ",
) -> tuple[str, bool]:
    """Read a file with optional line slicing and indentation.

    Returns (text, truncated_flag).
    """

    file_path = boundary.sanitize_path(path)
    boundary.assert_within_root(file_path)

    if not file_path.exists() or not file_path.is_file():
        raise FileNotFoundError(file_path)

    lines = file_path.read_text(encoding="utf-8").splitlines()
    selected = lines[offset : offset + limit]

    processed: list[str] = []
    for line in selected:
        trimmed = line
        if len(trimmed) > 400:
            trimmed = trimmed[:400] + "… [truncated line]"
        processed.append(trimmed)

    if mode == "indentation":
        processed = [indent + line for line in processed]
    elif mode != "slice":
        raise ValueError("mode must be 'slice' or 'indentation'")

    text = "\n".join(processed)
    return text, len(lines) > offset + limit


def tool_registrations(boundary: FsBoundary) -> list[ToolRegistration]:
    tool = ReadFileTool(boundary)

    def _end_event(validated: BaseModel, output: BaseModel) -> dict[str, object]:
        out = cast(ReadFileOutput, output)
        return {"truncated": out.truncated}

    return [
        ToolRegistration(
            name="read_file",
            description="Read file slice with optional indentation mode",
            input_model=ReadFileInput,
            output_model=ReadFileOutput,
            handler=cast(Callable[[ToolRequest], ToolResponse], tool.execute),
            result_adapter=lambda out: (cast(ReadFileOutput, out).text, cast(ReadFileOutput, out).truncated),
            end_event_builder=_end_event,
        )
    ]


__all__ = [
    "read_file",
    "tool_registrations",
    "ReadFileInput",
    "ReadFileOutput",
]
