"""Patch parsing utilities (unified diff + freeform envelope)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


class PatchParseError(Exception):
    """Raised when a patch cannot be parsed."""


FREEFORM_BEGIN = "*** Begin Patch"
FREEFORM_END = "*** End Patch"


@dataclass(frozen=True, slots=True)
class Hunk:
    start_old: int
    len_old: int
    start_new: int
    len_new: int
    lines: list[str]


@dataclass(frozen=True, slots=True)
class FilePatch:
    path: Path
    hunks: list[Hunk]


_HUNK_HEADER = re.compile(r"@@ -(\d+),?(\d+)? \+(\d+),?(\d+)? @@")


def extract_freeform(text: str) -> str:
    """Extract unified diff from a freeform apply_patch envelope."""

    begin = text.find(FREEFORM_BEGIN)
    end = text.find(FREEFORM_END)
    if begin == -1 or end == -1 or end <= begin:
        raise PatchParseError("freeform patch markers not found")
    payload = text[begin + len(FREEFORM_BEGIN) : end]
    return payload.strip()


def parse_unified_diff(diff_text: str) -> list[FilePatch]:
    """Parse a minimal unified diff into FilePatch structures."""

    lines = diff_text.splitlines()
    patches: list[FilePatch] = []
    idx = 0

    while idx < len(lines):
        line = lines[idx]
        if line.startswith("--- "):
            if idx + 1 >= len(lines) or not lines[idx + 1].startswith("+++ "):
                raise PatchParseError("missing +++ header")
            new_path = _normalize_path(lines[idx + 1][4:].strip().split("\t")[0])
            file_path = Path(new_path)
            idx += 2
            hunks, idx = _parse_hunks(lines, idx)
            patches.append(FilePatch(path=file_path, hunks=hunks))
        elif line.startswith("*** Update File:"):
            file_path = Path(_normalize_path(line.split(":", 1)[1].strip()))
            idx += 1
            hunks, idx = _parse_hunks(lines, idx)
            patches.append(FilePatch(path=file_path, hunks=hunks))
        else:
            idx += 1

    if not patches:
        raise PatchParseError("no file patches found")
    return patches


def _normalize_path(raw: str) -> str:
    parts = Path(raw).parts
    if parts and parts[0] in {"a", "b"}:
        parts = parts[1:]
    return str(Path(*parts))


def _parse_hunks(lines: list[str], idx: int) -> tuple[list[Hunk], int]:
    hunks: list[Hunk] = []
    while idx < len(lines) and lines[idx].startswith("@@ "):
        header = lines[idx]
        match = _HUNK_HEADER.match(header)
        if not match:
            raise PatchParseError(f"invalid hunk header: {header}")
        start_old = int(match.group(1))
        len_old = int(match.group(2) or "1")
        start_new = int(match.group(3))
        len_new = int(match.group(4) or "1")
        idx += 1
        hunk_lines: list[str] = []
        while idx < len(lines) and not lines[idx].startswith(("--- ", "*** Update File:")):
            if lines[idx].startswith("@@ "):
                break
            prefix = lines[idx][:1]
            if prefix not in (" ", "+", "-"):
                raise PatchParseError(f"invalid hunk line: {lines[idx]}")
            hunk_lines.append(lines[idx])
            idx += 1
        hunks.append(
            Hunk(
                start_old=start_old,
                len_old=len_old,
                start_new=start_new,
                len_new=len_new,
                lines=hunk_lines,
            )
        )
    return hunks, idx


__all__ = ["PatchParseError", "FilePatch", "Hunk", "parse_unified_diff", "extract_freeform"]
