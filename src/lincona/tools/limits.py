"""Shared output truncation utilities."""

from __future__ import annotations


def truncate_output(
    text: str, *, max_bytes: int = 8_192, max_lines: int = 200, marker: str = "[truncated]"
) -> tuple[str, bool]:
    """Truncate text by bytes and lines, returning (result, was_truncated).

    - Enforces both byte and line limits; whichever triggers first stops output.
    - Uses UTF-8 byte count for byte budgeting.
    - Appends a marker on a new line when truncation occurs.
    """

    truncated = False
    lines = text.splitlines(keepends=True)
    collected: list[str] = []
    bytes_used = 0

    for idx, line in enumerate(lines):
        if idx >= max_lines:
            truncated = True
            break

        encoded = line.encode("utf-8")
        if bytes_used + len(encoded) > max_bytes:
            truncated = True
            break

        collected.append(line)
        bytes_used += len(encoded)

    result = "".join(collected)
    if truncated:
        if not result.endswith("\n"):
            result += "\n"
        result += marker
    return result, truncated


__all__ = ["truncate_output"]
