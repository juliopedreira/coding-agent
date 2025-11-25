"""Recursive regex grep respecting filesystem boundary."""

from __future__ import annotations

import re
from pathlib import Path
from typing import cast

from pydantic import BaseModel, Field

from lincona.tools.fs import FsBoundary
from lincona.tools.registry import ToolRegistration


class GrepFilesInput(BaseModel):
    pattern: str = Field(description="Regex pattern to search for.")
    path: str = Field(default=".", description="Root directory to search under.")
    include: list[str] | None = Field(default=None, description="Optional glob filters to include.")
    limit: int = Field(default=200, ge=1, description="Maximum matches to return.")


class GrepFilesOutput(BaseModel):
    results: list[str] = Field(description="Matches formatted as path:line:content.")


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
    def handler(data: BaseModel) -> BaseModel:
        typed = cast(GrepFilesInput, data)
        results = grep_files(boundary, **typed.model_dump())
        return GrepFilesOutput(results=results)

    return [
        ToolRegistration(
            name="grep_files",
            description="Recursive regex search with include globs",
            input_model=GrepFilesInput,
            output_model=GrepFilesOutput,
            handler=handler,
            result_adapter=lambda out: cast(GrepFilesOutput, out).results,
        )
    ]


__all__ = [
    "grep_files",
    "tool_registrations",
    "GrepFilesInput",
    "GrepFilesOutput",
]
