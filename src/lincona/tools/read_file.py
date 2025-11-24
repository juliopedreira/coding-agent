"""File reading tool with slicing and indentation modes."""

from __future__ import annotations

from pathlib import Path

from lincona.tools.fs import FsBoundary


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
