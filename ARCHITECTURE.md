# Lincona Architecture (MVP_00 snapshot)

This document summarizes the current code structure with emphasis on config/persistence (Epic 2).

## Config
- File: `src/lincona/config.py`
- `Settings` (pydantic, frozen) with defaults: model `gpt-4.1-mini`, reasoning `medium`, `fs_mode=restricted`, `approval_policy=on-request`, `log_level=warning`.
- `load_settings`: precedence CLI > env (`OPENAI_API_KEY`) > config file > defaults; enforces 0o600 perms; optional create.
- `write_config`: serializes to TOML layout `[auth]`, `[model]`, `[runtime]`, `[logging]`.

## Paths
- File: `src/lincona/paths.py`
- `LINCONA_HOME` env overrides base directory; defaults to `~/.lincona`.

## Sessions & Persistence
- File: `src/lincona/sessions.py`
- `generate_session_id`: `YYYYMMDDHHMM-uuid4`.
- `Event` schema (pydantic, strict) + `Role` enum.
- `JsonlEventWriter`: append-only writer with optional `fsync_every`, explicit `sync()`; `iter_events` for validated reads.
- Helpers: `session_path`, `list_sessions`, `resume_session`, `delete_session` (all respect `LINCONA_HOME`).

## Logging
- File: `src/lincona/logging.py`
- `configure_session_logger`: per-session file handler, truncates to last N bytes (default 5MB; disable with `max_bytes=None`), warns on unknown log levels.
- `session_log_path` uses `LINCONA_HOME`.

## Shutdown
- File: `src/lincona/shutdown.py`
- `ShutdownManager`: registers callbacks, event writers, and loggers; runs once on SIGINT/SIGTERM/atexit; logs callback failures; restores prior signal handlers; `register_resources` convenience.

## CLI (stub)
- File: `src/lincona/cli.py`
- Placeholder entrypoint (version flag, stub message); to be replaced by TUI/tooling in later epics.

## Tests
- Config, sessions, logging, and shutdown have unit tests under `tests/` covering precedence, permissions, schema strictness, truncation, durability toggles, and shutdown ordering.

## Data locations
- `config.toml`, `sessions/<id>.jsonl`, `logs/<id>.log` under `LINCONA_HOME` (default `~/.lincona`).
