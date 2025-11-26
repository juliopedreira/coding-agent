"""Recursive regex grep respecting filesystem boundary."""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import cast

from pydantic import BaseModel, Field

from lincona.tools.base import Tool, ToolRequest, ToolResponse
from lincona.tools.fs import FsBoundary
from lincona.tools.registry import ToolRegistration


class GrepFilesInput(ToolRequest):
    pattern: str = Field(description="Regex(Python re) pattern to search for in files' lines.")
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
    results: list[FileMatches] = Field(
        description="Matches grouped per file. Each match includes line number, content, and optional truncation flag."
    )


class LineMatch(ToolResponse):
    line_num: int = Field(description="Line number (1-indexed) where the pattern matched.")
    line: str = Field(description="Line content (possibly truncated).")
    truncated: bool | None = Field(
        default=None, description="Present and true when the line was truncated to fit size limits."
    )


class FileMatches(ToolResponse):
    file: str = Field(description="File path of the matches (relative to boundary root when restricted).")
    matches: list[LineMatch] = Field(description="Matches found in this file.")


class GrepFilesTool(Tool[GrepFilesInput, GrepFilesOutput]):
    name = "grep_files"
    description = "Recursive regex search with include globs; returns path + line-number grouped results"
    InputModel = GrepFilesInput
    OutputModel = GrepFilesOutput

    def __init__(self, boundary: FsBoundary) -> None:
        self.boundary = boundary

    def execute(self, request: GrepFilesInput) -> GrepFilesOutput:
        results = grep_files(self.boundary, **request.model_dump())
        return GrepFilesOutput(results=results)


def _iter_files(root: Path, include: list[str] | None = None) -> Iterable[Path]:
    """Yield files under root lazily, honoring optional include globs."""

    if not root.is_dir():
        return
    for path in root.rglob("*"):
        if path.is_file():
            if include and not any(path.match(glob) for glob in include):
                continue
            yield path


def grep_files(
    boundary: FsBoundary,
    pattern: str,
    *,
    path: str | Path = ".",
    include: list[str] | None = None,
    limit: int = 200,
) -> list[FileMatches]:
    """Search files under path for regex pattern, grouping matches per file."""

    root = boundary.sanitize_path(path)
    boundary.assert_within_root(root)

    regex = re.compile(pattern)
    results: list[FileMatches] = []
    total_matches = 0
    root_path = boundary.root_path()

    current_file: FileMatches | None = None

    for file_path in _iter_files(root, include) or []:
        boundary.assert_within_root(file_path)
        try:
            text = file_path.read_text(encoding="utf-8", errors="ignore")
        except (OSError, UnicodeDecodeError):
            continue

        file_matches: list[LineMatch] = []
        for lineno, line in enumerate(text.splitlines(), start=1):
            if regex.search(line):
                truncated = None
                if len(line) > 1000:
                    line = line[:1000] + "… [truncated]"
                    truncated = True
                file_matches.append(LineMatch(line_num=lineno, line=line, truncated=truncated))
                total_matches += 1
                if total_matches >= limit:
                    break
        if file_matches:
            rel_path = file_path.relative_to(root_path) if root_path is not None else file_path.resolve()
            current_file = FileMatches(file=str(rel_path), matches=file_matches)
            results.append(current_file)
        if total_matches >= limit:
            break

    return results


def tool_registrations(boundary: FsBoundary) -> list[ToolRegistration]:
    tool = GrepFilesTool(boundary)

    def _end_event(validated: BaseModel, output: BaseModel) -> dict[str, object]:
        out = cast(GrepFilesOutput, output)
        match_count = sum(len(file.matches) for file in out.results)
        return {"matches": match_count}

    return [
        ToolRegistration(
            name="grep_files",
            description="Recursive regex search with include globs; returns grouped path+line matches.",
            input_model=GrepFilesInput,
            output_model=GrepFilesOutput,
            handler=cast(Callable[[ToolRequest], ToolResponse], tool.execute),
            result_adapter=lambda out: [fm.model_dump(exclude_none=True) for fm in cast(GrepFilesOutput, out).results],
            end_event_builder=_end_event,
        )
    ]


__all__ = [
    "grep_files",
    "tool_registrations",
    "GrepFilesInput",
    "GrepFilesOutput",
]
