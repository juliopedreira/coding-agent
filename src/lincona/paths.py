"""Common path utilities for Lincona."""

from __future__ import annotations

import os
from pathlib import Path


def get_lincona_home() -> Path:
    """Return the base Lincona directory, honoring LINCONA_HOME if set."""

    env_path = os.environ.get("LINCONA_HOME")
    return Path(env_path).expanduser() if env_path else Path.home() / ".lincona"


__all__ = ["get_lincona_home"]
