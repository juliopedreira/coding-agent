"""Recursive regex grep respecting filesystem boundary."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import cast

from pydantic import BaseModel, Field

from lincona.tools.base import Tool, ToolRequest, ToolResponse
from lincona.tools.fs import FsBoundary
from lincona.tools.registry import ToolRegistration


class GrepFilesInput(ToolRequest):
    pattern: str = Field(description="Regex pattern to search for.")
    path: str = Field(default=".", description="Root directory to search under.")
    include: list[str] | None = Field(default=None, description="Optional glob filters to include.")
    limit: int = Field(default=200, ge=1, description="Maximum matches to return.")

    @classmethod
    def model_validate(cls, value: object) -> GrepFilesInput:  # type: ignore[override]
        if isinstance(value, dict) and isinstance(value.get("include"), str):
            raw = value["include"].strip()
            if raw in ("", "[]"):
                value = {**value, "include": None}
            else:
                try:
                    value = {**value, "include": json.loads(raw)}
                except Exception:
                    value = {**value, "include": [part.strip() for part in raw.split(",") if part.strip()]}
        return super().model_validate(value)


class GrepFilesOutput(ToolResponse):
    results: list[str] = Field(description="Matches formatted as path:line:content.")


class GrepFilesTool(Tool[GrepFilesInput, GrepFilesOutput]):
    name = "grep_files"
    description = "Recursive regex search with include globs"
    InputModel = GrepFilesInput
    OutputModel = GrepFilesOutput

    def __init__(self, boundary: FsBoundary) -> None:
        self.boundary = boundary

    def execute(self, request: GrepFilesInput) -> GrepFilesOutput:
        results = grep_files(self.boundary, **request.model_dump())
        return GrepFilesOutput(results=results)


def _iter_files(root: Path, include: list[str] | None = None) -> list[Path]:
    files: list[Path] = []
    if not root.is_dir():
        return files
    for path in root.rglob("*"):
        if path.is_file():
            if include and not any(path.match(glob) for glob in include):
                continue
            files.append(path)
    return files


def grep_files(
    boundary: FsBoundary,
    pattern: str,
    *,
    path: str | Path = ".",
    include: list[str] | None = None,
    limit: int = 200,
) -> list[str]:
    """Search files under path for regex pattern."""

    root = boundary.sanitize_path(path)
    boundary.assert_within_root(root)

    regex = re.compile(pattern)
    results: list[str] = []

    files = _iter_files(root, include)
    for file_path in files:
        boundary.assert_within_root(file_path)
        try:
            text = file_path.read_text(encoding="utf-8", errors="ignore")
        except (OSError, UnicodeDecodeError):
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            match = regex.search(line)
            if match:
                results.append(f"{file_path.relative_to(root)}:{lineno}:{line}")
                if len(results) >= limit:
                    return results

    return results


def tool_registrations(boundary: FsBoundary) -> list[ToolRegistration]:
    tool = GrepFilesTool(boundary)

    def _end_event(validated: BaseModel, output: BaseModel) -> dict[str, object]:
        out = cast(GrepFilesOutput, output)
        return {"matches": len(out.results)}

    return [
        ToolRegistration(
            name="grep_files",
            description="Recursive regex search with include globs",
            input_model=GrepFilesInput,
            output_model=GrepFilesOutput,
            handler=cast(Callable[[ToolRequest], ToolResponse], tool.execute),
            result_adapter=lambda out: cast(GrepFilesOutput, out).results,
            end_event_builder=_end_event,
        )
    ]


__all__ = [
    "grep_files",
    "tool_registrations",
    "GrepFilesInput",
    "GrepFilesOutput",
]
