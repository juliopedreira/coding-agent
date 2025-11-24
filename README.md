# Lincona

Linux-only interactive coding agent CLI.

## Prerequisites
- Python 3.11+
- Poetry (`pipx install poetry` recommended)

## Setup (venv in project)
```sh
python3 -m venv .venv
source .venv/bin/activate
POETRY_VIRTUALENVS_IN_PROJECT=1 poetry install --with dev
```
or simply:
```sh
POETRY_VIRTUALENVS_IN_PROJECT=1 poetry install --with dev
```
Poetry will place the virtualenv in `.venv/`.

## Useful Commands (Makefile)
- `make install` – install deps with dev extras
- `make format` – black + isort
- `make lint` – ruff
- `make typecheck` – mypy (src)
- `make test` – pytest (with coverage gates)
- `make ci` – format + lint + typecheck + test
- `make lock` – regenerate `poetry.lock`
- `make pre-commit-install` – install git hooks

## Pre-commit
Install hooks after setup:
```sh
POETRY_VIRTUALENVS_IN_PROJECT=1 poetry run pre-commit install
```
Run on demand:
```sh
POETRY_VIRTUALENVS_IN_PROJECT=1 poetry run pre-commit run --all-files
```

## Quick start
- Show version: `POETRY_VIRTUALENVS_IN_PROJECT=1 poetry run lincona --version`
- Run the placeholder CLI: `POETRY_VIRTUALENVS_IN_PROJECT=1 poetry run lincona`
  - Currently prints a stub message; real TUI/commands arrive in later epics.

## Configuration & data directories
- Base directory: `~/.lincona/` (override with env `LINCONA_HOME=/custom/path`).
- Files:
  - `config.toml` – persisted defaults (see docs/mvp_00/03_EPIC_02.md).
  - `sessions/<id>.jsonl` – append-only session transcripts.
  - `logs/<id>.log` – per-session plaintext logs (truncated to 5MB by default).
- Environment: `OPENAI_API_KEY` overrides `api_key` in config.

## Architecture quick peek
- Config & paths: `lincona.config`, `lincona.paths` load persisted defaults from `~/.lincona/config.toml` with precedence CLI > env > file > defaults.
- Persistence: `lincona.sessions` manages JSONL event streams and IDs; `lincona.logging` creates per-session logs with truncation.
- Shutdown: `lincona.shutdown.ShutdownManager` closes writers/loggers safely on SIGINT/SIGTERM/atexit.
- OpenAI client: `lincona.openai_client` offers an async Responses client with streaming parser, pluggable transports (HTTP/mock), back-pressure helper, error events, logging hook, and base URL override.
- Tools core (Epic 4 in progress): `lincona.tools` implements filesystem boundaries, output limits, file tools (`list_dir`, `read_file`, `grep_files`), patch apply (unified + freeform), shell and PTY exec, approval guard, and tool router.
- CLI: `lincona.cli` stub (TUI and tooling arrive in later epics).
See `ARCHITECTURE.md` for details.

## OpenAI Responses client (Epic 3)
- Package: `lincona.openai_client`.
- Typical usage:
```python
from lincona.config import load_settings
from lincona.openai_client import (
    HttpResponsesTransport,
    OpenAIResponsesClient,
    ConversationRequest,
    Message,
    MessageRole,
)

settings = load_settings()
transport = HttpResponsesTransport(api_key=settings.api_key or "test-key")
client = OpenAIResponsesClient(
    transport,
    default_model=settings.model,
    default_reasoning_effort=settings.reasoning_effort.value,
    default_timeout=60.0,
)

request = ConversationRequest(
    messages=[Message(role=MessageRole.USER, content="Hello")],
    model=None,  # falls back to default_model above
)

async for event in client.submit(request):
    ...  # handle TextDelta/ToolCall*/MessageDone/ErrorEvent
```
- Swap `HttpResponsesTransport` with `MockResponsesTransport([...])` in tests to feed canned SSE chunks; parsing is handled by `parse_stream`.

## Maintenance tips
- After changing dependencies, regenerate the lockfile: `make lock`
- If the virtualenv breaks, remove `.venv/` and run `make install`
