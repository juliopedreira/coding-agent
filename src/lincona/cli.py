"""Stub command-line interface for Lincona.

This will be expanded in later epics to launch the TUI and tool subcommands.
"""

from __future__ import annotations

import argparse
import sys

from lincona import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="lincona",
        description="Lincona interactive coding agent (stub entrypoint).",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
        help="Show version and exit.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    parser.parse_args(argv)
    print("Lincona CLI placeholder. Functionality will arrive in later epics.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
