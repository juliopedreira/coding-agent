"""Tool registry and aggregation.

Each tool module exports ``tool_registrations`` which yields one or more
``ToolRegistration`` instances built with the provided boundary/pty_manager.
``get_tool_registrations`` aggregates them for the router.
"""

from __future__ import annotations

from collections.abc import Iterable

from lincona.tools.apply_patch import tool_registrations as apply_patch_registrations

# Alias to avoid circular imports
from lincona.tools.exec_pty import PtyManager
from lincona.tools.exec_pty import tool_registrations as exec_registrations
from lincona.tools.fs import FsBoundary
from lincona.tools.grep_files import tool_registrations as grep_registrations
from lincona.tools.list_dir import tool_registrations as list_dir_registrations
from lincona.tools.read_file import tool_registrations as read_file_registrations
from lincona.tools.registry import ToolRegistration
from lincona.tools.shell import tool_registrations as shell_registrations


def get_tool_registrations(boundary: FsBoundary, pty_manager: PtyManager | None = None) -> list[ToolRegistration]:
    registrations: list[ToolRegistration] = []

    def extend(items: Iterable[ToolRegistration]) -> None:
        registrations.extend(items)

    extend(list_dir_registrations(boundary))
    extend(read_file_registrations(boundary))
    extend(grep_registrations(boundary))
    extend(apply_patch_registrations(boundary))
    extend(shell_registrations(boundary))
    extend(exec_registrations(boundary, pty_manager))

    return registrations


__all__ = ["get_tool_registrations", "ToolRegistration", "PtyManager", "FsBoundary"]
