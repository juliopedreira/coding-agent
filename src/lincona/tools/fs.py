"""Filesystem boundary helpers for tools."""

from __future__ import annotations

from pathlib import Path

from lincona.config import FsMode


class FsViolationError(Exception):
    """Raised when a path escapes the allowed filesystem boundary."""


class FsBoundary:
    """Enforce filesystem boundaries for tool execution."""

    def __init__(self, fs_mode: FsMode, root: Path | None = None) -> None:
        self.fs_mode = fs_mode
        if fs_mode == FsMode.RESTRICTED:
            self.root: Path | None = (root or Path.cwd()).resolve()
        else:
            self.root = None  # unrestricted

    def root_path(self) -> Path | None:
        return self.root

    def sanitize_path(self, raw_path: str | Path) -> Path:
        """Return an absolute, normalized path respecting the boundary."""

        path = Path(raw_path)
        if not path.is_absolute() and self.root is not None:
            path = self.root / path
        resolved = path.resolve(strict=False)

        if self.root is not None:
            if not self._is_within(resolved):
                raise FsViolationError(f"path '{raw_path}' escapes restricted root {self.root}")
        return resolved

    def sanitize_workdir(self, workdir: str | Path | None) -> Path:
        """Validate and return a working directory, defaulting to root or cwd."""

        if workdir is None:
            return self.root if self.root is not None else Path.cwd()
        return self.sanitize_path(workdir)

    def assert_within_root(self, path: Path) -> None:
        """Raise if the resolved path escapes the boundary."""

        if self.root is None:
            return
        resolved = path.resolve(strict=False)
        if not self._is_within(resolved):
            raise FsViolationError(f"path '{path}' escapes restricted root {self.root}")

    def _is_within(self, path: Path) -> bool:
        """Return True if ``path`` is inside the boundary. Assumes ``path`` is already resolved."""

        if self.root is None:
            return True
        try:
            path.relative_to(self.root)
            return True
        except ValueError:
            return False
