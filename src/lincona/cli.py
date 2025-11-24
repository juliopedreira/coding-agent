"""Stub command-line interface for Lincona.

This will be expanded in later epics to launch the TUI and tool subcommands.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

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
    parser.add_argument(
        "--debug",
        nargs="?",
        const="lincona-debug.log",
        metavar="LOGFILE",
        help="Enable debug logging to LOGFILE (default: lincona-debug.log in current directory).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if getattr(args, "debug", None):
        _configure_debug_logging(Path(args.debug))
        logging.getLogger(__name__).debug("debug mode enabled")

    print("Lincona CLI placeholder. Functionality will arrive in later epics.")
    return 0


def _configure_debug_logging(log_path: Path) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.DEBUG,
        filename=str(log_path),
        filemode="w",
        format="%(asctime)s %(levelname)s %(filename)s:%(lineno)d %(message)s",
        force=True,
    )


if __name__ == "__main__":
    sys.exit(main())
