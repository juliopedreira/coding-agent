"""Recursive regex grep respecting filesystem boundary."""

from __future__ import annotations

import re
from pathlib import Path

from lincona.tools.fs import FsBoundary


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
