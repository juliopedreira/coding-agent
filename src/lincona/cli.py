"""Console entrypoint for Lincona.

Provides a minimal REPL-style agent with tool support plus standalone tool
invocations and session/config helpers. Designed to be small but functional
for MVP testing on Linux terminals.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Any

from lincona import __version__
from lincona.config import ApprovalPolicy, FsMode, LogLevel, ReasoningEffort, Settings, load_settings
from lincona.paths import get_lincona_home
from lincona.repl import AgentRunner
from lincona.sessions import delete_session, list_sessions
from lincona.tools.fs import FsBoundary
from lincona.tools.router import ToolRouter, tool_specs


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="lincona",
        description="Lincona interactive coding agent",
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
    parser.add_argument("--model", help="Override default model id")
    parser.add_argument("--reasoning", choices=[e.value for e in ReasoningEffort], help="Reasoning effort override")
    parser.add_argument("--fs-mode", choices=[e.value for e in FsMode], dest="fs_mode", help="Filesystem mode")
    parser.add_argument(
        "--approval",
        choices=[e.value for e in ApprovalPolicy],
        dest="approval_policy",
        help="Approval policy override",
    )
    parser.add_argument(
        "--log-level",
        choices=[e.value for e in LogLevel],
        dest="log_level",
        help="Log level override",
    )
    parser.add_argument("--config-path", dest="config_path", help="Path to config.toml")

    subparsers = parser.add_subparsers(dest="command")

    # chat / repl
    chat_parser = subparsers.add_parser("chat", help="Interactive REPL chat (default)")
    chat_parser.set_defaults(command="chat")

    # tool invocation
    tool_parser = subparsers.add_parser("tool", help="Invoke a single tool")
    tool_parser.add_argument("name", choices=[spec["function"]["name"] for spec in tool_specs()], help="Tool name")
    tool_parser.add_argument("--json", dest="json_payload", help="JSON payload with tool arguments")
    tool_parser.add_argument("--arg", action="append", default=[], help="key=value pairs for tool args")

    # sessions helper
    sessions_parser = subparsers.add_parser("sessions", help="List/show/remove sessions")
    sessions_sub = sessions_parser.add_subparsers(dest="sessions_cmd", required=True)
    sessions_sub.add_parser("list", help="List sessions")
    show_parser = sessions_sub.add_parser("show", help="Show a session JSONL")
    show_parser.add_argument("session_id", help="Session id")
    rm_parser = sessions_sub.add_parser("rm", help="Delete a session")
    rm_parser.add_argument("session_id", help="Session id")

    # config helper
    config_parser = subparsers.add_parser("config", help="Config helpers")
    config_sub = config_parser.add_subparsers(dest="config_cmd", required=True)
    config_sub.add_parser("path", help="Print config path")
    config_sub.add_parser("print", help="Print resolved settings")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if getattr(args, "debug", None):
        _configure_debug_logging(Path(args.debug))
        logging.getLogger(__name__).debug("debug mode enabled")

    overrides = _collect_overrides(args)
    settings = load_settings(cli_overrides=overrides, config_path=args.config_path)

    command = args.command or "chat"
    if command == "chat":
        asyncio.run(_run_chat(settings))
        return 0
    if command == "tool":
        return _run_tool(settings, args)
    if command == "sessions":
        return _run_sessions(args)
    if command == "config":
        return _run_config(settings, args)

    parser.error(f"unknown command {command}")
    return 1


async def _run_chat(settings: Settings) -> None:
    runner = AgentRunner(settings)
    await runner.repl()


def _run_tool(settings: Settings, args: argparse.Namespace) -> int:
    boundary = FsBoundary(settings.fs_mode)
    router = ToolRouter(boundary, settings.approval_policy)

    payload: dict[str, Any] = {}
    if args.json_payload:
        payload = json.loads(args.json_payload)
    for pair in args.arg:
        if "=" not in pair:
            raise SystemExit("--arg expects key=value")
        key, value = pair.split("=", 1)
        payload[key] = value

    try:
        result = router.dispatch(args.name, **payload)
    except Exception as exc:  # pragma: no cover - CLI surface
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(result, indent=2))
    return 0


def _run_sessions(args: argparse.Namespace) -> int:
    home = get_lincona_home()
    if args.sessions_cmd == "list":
        sessions = list_sessions(home / "sessions")
        for info in sessions:
            print(f"{info.session_id} {info.modified_at.isoformat()} {info.size_bytes}B {info.path}")
        return 0
    if args.sessions_cmd == "show":
        path = home / "sessions" / f"{args.session_id}.jsonl"
        if not path.exists():
            print("not found", file=sys.stderr)
            return 1
        print(path.read_text(encoding="utf-8"))
        return 0
    if args.sessions_cmd == "rm":
        delete_session(args.session_id, home / "sessions")
        return 0
    return 1


def _run_config(settings: Settings, args: argparse.Namespace) -> int:
    if args.config_cmd == "path":
        print(get_lincona_home() / "config.toml")
        return 0
    if args.config_cmd == "print":
        print(settings.model_dump_json(indent=2))
        return 0
    return 1


def _collect_overrides(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "model": args.model,
        "reasoning_effort": args.reasoning,
        "fs_mode": args.fs_mode,
        "approval_policy": args.approval_policy,
        "log_level": args.log_level,
    }


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
