"""Atomic patch application with filesystem boundary enforcement."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from lincona.tools.fs import FsBoundary
from lincona.tools.patch_parser import Hunk, PatchParseError, extract_freeform, parse_unified_diff


class PatchApplyError(Exception):
    """Raised when a patch cannot be applied cleanly."""


@dataclass(frozen=True, slots=True)
class PatchResult:
    path: Path
    bytes_written: int
    created: bool


def apply_patch(boundary: FsBoundary, patch_text: str, *, freeform: bool = False) -> list[PatchResult]:
    """Apply a unified diff (or freeform envelope) atomically within the boundary."""

    diff_text = extract_freeform(patch_text) if freeform else patch_text
    try:
        file_patches = parse_unified_diff(diff_text)
    except PatchParseError:
        raise
    results: list[PatchResult] = []

    for file_patch in file_patches:
        if getattr(file_patch, "delete", False) and str(file_patch.path) == "/dev/null":
            # nothing to delete
            continue

        target = boundary.sanitize_path(file_patch.path)
        boundary.assert_within_root(target)

        original_lines: list[str] = []
        had_trailing = False
        exists = target.exists()
        if exists:
            if target.is_dir():
                raise PatchApplyError(f"target {target} is a directory")
            original_text = target.read_text(encoding="utf-8")
            had_trailing = original_text.endswith("\n") or original_text.endswith("\r\n")
            original_lines = original_text.splitlines()
        else:
            if file_patch.hunks and file_patch.hunks[0].start_old > 0:
                raise PatchApplyError("cannot delete or modify non-existent file")

        # handle deletions when new path is /dev/null (represented as delete flag on FilePatch)
        if getattr(file_patch, "delete", False):
            if exists:
                target.unlink()
                results.append(PatchResult(path=target, bytes_written=0, created=False))
            continue

        new_lines = _apply_hunks(original_lines, file_patch.hunks)
        content = _join_preserve_trailing(new_lines, had_trailing)

        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=target.parent, delete=False) as tmp:
            tmp.write(content)
            tmp.flush()
            os.fsync(tmp.fileno())
            tmp_path = Path(tmp.name)
        tmp_path.replace(target)
        results.append(PatchResult(path=target, bytes_written=len(content.encode("utf-8")), created=not exists))

    return results


def _apply_hunks(original: list[str], hunks: list[Hunk]) -> list[str]:
    current = original[:]

    for hunk in hunks:
        start_idx = max(hunk.start_old - 1, 0)
        if start_idx > len(current):
            raise PatchApplyError("hunk start out of range")

        pre = current[:start_idx]
        idx = start_idx
        new_chunk: list[str] = []

        for line in hunk.lines:
            prefix, content = line[0], line[1:]
            if prefix == " ":
                if idx >= len(current) or current[idx] != content:
                    raise PatchApplyError("context mismatch during apply")
                new_chunk.append(content)
                idx += 1
            elif prefix == "-":
                if idx >= len(current) or current[idx] != content:
                    raise PatchApplyError("delete mismatch during apply")
                idx += 1
            elif prefix == "+":
                new_chunk.append(content)
            else:
                raise PatchApplyError(f"invalid hunk line: {line}")

        post = current[idx:]
        current = pre + new_chunk + post

    return current


def _join_preserve_trailing(new_lines: Sequence[str], had_trailing: bool) -> str:
    """Join lines preserving trailing newline if present in original text."""

    text = "\n".join(new_lines)
    if had_trailing and new_lines:
        if not text.endswith("\n"):
            text += "\n"
    return text


__all__ = ["apply_patch", "PatchApplyError", "PatchResult"]
