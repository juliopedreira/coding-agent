# Lincona Architecture

Audience: developers and maintainers. This document explains the internal layout, control flow, and defaults; user-facing setup lives in `README.md`.

## System Overview
- Text-based CLI (`lincona`) hosts a REPL (`AgentRunner`) that streams OpenAI Responses and can invoke local tools.
- A tool router enforces filesystem boundaries and approval policy before executing tools.
- Sessions and logs are persisted under `~/.lincona/` for replay and debugging; shutdown handlers flush state safely.

## Control Flow (happy path)
1) **CLI entry (`src/lincona/cli.py`)** parses args, resolves settings (auto-creating `~/.lincona/config.toml` if missing), and starts the REPL.
2) **Agent runner (`src/lincona/repl.py`)** keeps chat history, sends a `ConversationRequest` to the OpenAI client with tool schemas, and streams `ResponseEvent`s.
3) **OpenAI client (`src/lincona/openai_client/`)** builds payloads, uses the configured transport (HTTP or mock), parses SSE into typed events, and surfaces tool-call lifecycles.
4) **Tool router (`src/lincona/tools/router.py`)** maps tool calls to implementations, applying `FsBoundary` checks and `ApprovalPolicy` before dispatch.
5) **Tools (`src/lincona/tools/`)** perform bounded actions (list/read files, grep, apply_patch JSON/freeform, shell, exec_pty). Outputs are serialized back into the conversation.
6) **Persistence**: each turn is appended to `sessions/<id>/events.jsonl`; logs go to `logs/<id>.log`; `ShutdownManager` ensures writers/PTYs close on exit.

## Modules & Responsibilities
- **Config & paths** (`config.py`, `paths.py`): immutable `Settings`; precedence CLI > env > config file > defaults; config at `~/.lincona/config.toml` (mode 600) and created on first run. Defaults: `model=gpt-5.1-codex-mini`; `allowed_models=["gpt-5","gpt-5-codex","gpt-5-mini","gpt-5-nano","gpt-5-pro","gpt-5.1","gpt-5.1-codex","gpt-5.1-codex-mini"]`; `reasoning_effort=medium`; `fs_mode=restricted`; `approval_policy=on-request`; `log_level=info`.
- **OpenAI Responses client** (`openai_client/`): typed requests/events, HTTP + mock transports, SSE parsing with back-pressure and tool-call buffering.
- **Tools core** (`tools/`): `FsBoundary`, `limits`, file tools, patch tools, shell/PTY, approval guard, registry + router. Tools follow the OpenAI Agents spec and use Pydantic models per `src/lincona/tools/AGENTS.md`.
- **Sessions & logging** (`sessions.py`, `logging.py`, `shutdown.py`): JSONL event writer/reader, session ID generation (`YYYYMMDDHHMM-uuid4`), per-session file logger with 5 MB truncation guard, graceful shutdown coordination.
- **CLI** (`cli.py`): entrypoint, tool subcommand runner, session helpers (`list/show/rm`), config helpers (`path/print`).

## Data Layout (default `~/.lincona/`)
- `config.toml` (auto-created on first run)
- `sessions/<id>/events.jsonl`
- `logs/<id>.log`

## Testing & Quality
- Unit tests cover config precedence/permissions, sessions/logging/shutdown, OpenAI client (types/transport/parsing/client), tools, and REPL behavior.
- Coverage gate enforced via `make ci`; see `tests/` for contract expectations (e.g., truncation markers, approval handling, tool schemas).

## Extensibility Notes
- Add tools by following `src/lincona/tools/AGENTS.md` and registering via `tools/__init__.py`.
- Use `MockResponsesTransport` to feed canned SSE streams in tests; avoid network I/O in unit tests.
- Respect `FsBoundary` and `ApprovalPolicy` whenever adding new mutating behaviors.
