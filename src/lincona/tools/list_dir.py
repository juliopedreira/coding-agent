"""Directory listing tool respecting filesystem boundaries."""

from __future__ import annotations

from collections import deque
from pathlib import Path

from lincona.tools.fs import FsBoundary


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
