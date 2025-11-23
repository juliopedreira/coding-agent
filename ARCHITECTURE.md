# Lincona Architecture (MVP_00 snapshot)

High-level view of the current codebase (Epics 1–3 complete; TUI/tools arrive later).

## Runtime core
- **Config & paths** (`src/lincona/config.py`, `paths.py`): immutable `Settings`, precedence CLI > env > file > defaults; config at `~/.lincona/config.toml` (mode 600); `LINCONA_HOME` override for all data.
- **Persistence** (`src/lincona/sessions.py`): strict `Event` schema, JSONL writer/reader, session IDs `YYYYMMDDHHMM-uuid4`, helpers to list/resume/delete.
- **Logging** (`src/lincona/logging.py`): per-session file logger, truncation guard (default 5 MB), level validation.
- **Shutdown** (`src/lincona/shutdown.py`): one-shot manager for callbacks/loggers/writers; restores signal handlers; safe on SIGINT/SIGTERM/atexit.

## OpenAI Responses client (Epic 3)
- Package: `lincona.openai_client/`
  - `types.py`: request/response dataclasses, event union, error classes.
  - `transport.py`: protocol + HTTP transport (headers, retry-after parsing, logging hook, base_url override) and mock transport.
  - `parsing.py`: SSE → events, tool-call lifecycle, size guards, bounded `consume_stream` for back-pressure.
  - `client.py`: assembles payloads with defaults, streams events, emits `ErrorEvent` on failures.

## CLI entry
- `src/lincona/cli.py`: placeholder CLI stub (TUI/tooling to be added in later epics).

## Data layout (default `~/.lincona/`)
- `config.toml`
- `sessions/<id>.jsonl`
- `logs/<id>.log`

## Testing
- Unit tests cover config precedence/permissions, sessions, logging/shutdown, OpenAI client (types/transport/parsing/client/back-pressure/errors). Coverage gate ≥80% per source file via `make ci`.
