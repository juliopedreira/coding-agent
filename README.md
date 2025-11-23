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
See `ARCHITECTURE.md` for a current overview of config loading, persistence, logging, and shutdown handling.

## Maintenance tips
- After changing dependencies, regenerate the lockfile: `make lock`
- If the virtualenv breaks, remove `.venv/` and run `make install`
