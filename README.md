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

## Configuration & data
- Location: `~/.lincona/` (override with `LINCONA_HOME=/custom/path`).
- Files (created on first run): `config.toml`, `sessions/<id>.jsonl`, `logs/<id>.log` (logs truncated to 5MB). `config.toml` is written with `0600` permissions.
- Load order: CLI flags > environment (`OPENAI_API_KEY`, etc.) > `config.toml` > built-ins.
- Inspect: `POETRY_VIRTUALENVS_IN_PROJECT=1 poetry run lincona config path` and `... config print`.

### `config.toml` reference
```toml
[auth]
api_key = "sk-..."                # or set OPENAI_API_KEY

[model]
id = "gpt-5.1-codex-mini"         # must exist in [models."<id>"] or start with "gpt-5"
reasoning_effort = "medium"       # none|minimal|low|medium|high (optional override)
verbosity = "medium"              # low|medium|high (optional override)

[models."gpt-5.1-codex-mini"]     # capability table for the model
reasoning_effort = ["none","minimal","low","medium","high"]
default_reasoning = "none"
verbosity = ["low","medium","high"]
default_verbosity = "medium"

[runtime]
fs_mode = "restricted"            # restricted|unrestricted (tool filesystem boundary)
approval_policy = "on-request"    # never|on-request|always (tool approval prompts)

[logging]
log_level = "info"                # debug|info|warning|error
```
Notes:
- `OPENAI_API_KEY` overrides `[auth].api_key`; blanks are ignored.
- To allow an additional model, add another `[models."<id>"]` block with its supported `reasoning_effort`/`verbosity`. If the `model` id starts with `gpt-5` and is not listed, Lincona reuses the seed capabilities above.
- Avoid committing `config.toml`; keep the key out of version control.

## Where to learn more
- Developer internals and module layout: see `ARCHITECTURE.md`.
- Additional specs: `docs/mvp_00/`.

## Maintenance tips
- After changing dependencies, regenerate the lockfile: `make lock`
- If the virtualenv breaks, remove `.venv/` and run `make install`
