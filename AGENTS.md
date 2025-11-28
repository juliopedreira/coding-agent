# AGENTS GUIDE (Lincona)

Single source of truth for agent behavior, tooling, and guardrails when operating inside this repository.

## Authority & Scope
- Obey user instructions unless they violate this file.
- Stay within repository workspace plus /tmp

## Useful commands
- `make install` - creates .venv if needed, and installs dependencies
- `make ci` - formats, lints, checks and tests the project
- `POETRY_VIRTUALENVS_IN_PROJECT=1 poetry <...>` - for using poetry

## Useful doc
Read it, and keep it updated. 
- [README.md](README.md) - What the project does, and how to use it (install, configure, run, operate, etc.). Target: Users.
- [ARCHITECTURE.md](ARCHITECTURE.md) - Project internal software architecture. Target: Developers.