# Lincona

Linux-only interactive coding agent CLI.

Audience: users/operators (how to install, configure, run).

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
- Set `OPENAI_API_KEY` in your environment.
- Show version: `POETRY_VIRTUALENVS_IN_PROJECT=1 poetry run lincona --version`
- Start chat: `POETRY_VIRTUALENVS_IN_PROJECT=1 poetry run lincona chat`
  - Slash commands: `/help`, `/newsession`, `/model:list`, `/model:set <id>`, `/reasoning <low|medium|high>`, `/approvals <never|on-request|always>`, `/fsmode <restricted|unrestricted>`, `/quit`.
- Run a tool directly: `POETRY_VIRTUALENVS_IN_PROJECT=1 poetry run lincona tool list_dir --arg path=. --arg depth=1`
- Inspect sessions: `POETRY_VIRTUALENVS_IN_PROJECT=1 poetry run lincona sessions list`

## Configuration & data directories
- Base directory: `~/.lincona/` (override with env `LINCONA_HOME=/custom/path`).
- Files (created on first run if missing):
  - `config.toml` – persisted defaults.
  - `sessions/<id>.jsonl` – append-only session transcripts.
  - `logs/<id>.log` – per-session plaintext logs (truncated to 5MB by default).
- Environment: `OPENAI_API_KEY` overrides `api_key` in config.
- Models: default `gpt-5.1-codex-mini`; allowed set by `[model].allowed` (defaults to `["gpt-5","gpt-5-codex","gpt-5-mini","gpt-5-nano","gpt-5-pro","gpt-5.1","gpt-5.1-codex","gpt-5.1-codex-mini"]`). `/model:set` must pick from that list.

Example `~/.lincona/config.toml`:
```toml
api_key = "sk-..."                    # or use env OPENAI_API_KEY
[model]
id = "gpt-5.1-codex-mini"
allowed = ["gpt-5","gpt-5-codex","gpt-5-mini","gpt-5-nano","gpt-5-pro","gpt-5.1","gpt-5.1-codex","gpt-5.1-codex-mini"]
reasoning_effort = "medium"
[runtime]
fs_mode = "restricted"
approval_policy = "on-request"
[logging]
log_level = "info"
```

## Where to learn more
- Developer internals and module layout: see `ARCHITECTURE.md`.
- Additional specs: `docs/mvp_00/`.

## Maintenance tips
- After changing dependencies, regenerate the lockfile: `make lock`
- If the virtualenv breaks, remove `.venv/` and run `make install`
