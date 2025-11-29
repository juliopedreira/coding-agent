# Lincona Architecture

Audience: developers and maintainers. This document explains the internal layout, control flow, and defaults; user-facing setup lives in `README.md`.

## System Overview
- Text-based CLI (`lincona`) hosts a REPL (`AgentRunner`) that streams OpenAI Responses and can invoke local tools.
- Authentication is pluggable: API-key mode talks to `api.openai.com`; ChatGPT OAuth mode spins up a local PKCE login server, exchanges tokens, and targets the ChatGPT backend.
- A tool router enforces filesystem boundaries and approval policy before executing tools.
- Sessions, logs, and auth metadata are persisted under `~/.lincona/`; shutdown handlers flush state safely.

## Control Flow (happy path)
1) **CLI entry (`src/lincona/cli.py`)** parses args, resolves settings (auto-creating `~/.lincona/config.toml` if missing), configures the `AuthManager`, and either launches the REPL or handles helper subcommands (sessions/config/auth).
2) **Agent runner (`src/lincona/repl.py`)** keeps chat history, sends a `ConversationRequest` to the OpenAI client with tool schemas, and streams `ResponseEvent`s. Slash commands can change models, FS mode, or trigger `/auth login|logout|status` without leaving the session.
3) **OpenAI client (`src/lincona/openai_client/`)** builds payloads, uses the configured transport (HTTP or mock), parses SSE into typed events, and surfaces tool-call lifecycles.
4) **Tool router (`src/lincona/tools/router.py`)** maps tool calls to implementations, applying `FsBoundary` checks and `ApprovalPolicy` before dispatch.
5) **Tools (`src/lincona/tools/`)** perform bounded actions (list/read files, grep, apply_patch JSON/freeform, shell, exec_pty). Outputs are serialized back into the conversation.
6) **Persistence**: each turn is appended to `sessions/<id>/events.jsonl`; logs go to `logs/<id>.log`; `ShutdownManager` ensures writers/PTYs close on exit.

## Modules & Responsibilities
- **Config & paths** (`config.py`, `paths.py`): immutable `Settings`; precedence CLI > env > config file > defaults; config at `~/.lincona/config.toml` (mode 600) and created on first run. Defaults: `model=gpt-5.1-codex-mini`; `auth_mode=api_key`; `auth_client_id=app_EMoamEEZ73f0CkXaXp7hrann`; `auth_login_port=1455`; `allowed_models=[...]`; `reasoning_effort=medium`; `fs_mode=restricted`; `approval_policy=on-request`; `log_level=info`.
- **Auth** (`auth.py`): `AuthManager` encapsulates the PKCE login server (localhost listener + browser launch), token exchange/persistence (`auth.json`, mode 600), lazy refresh, bearer selection, and account metadata exposure for headers/UI.
- **OpenAI Responses client** (`openai_client/`): typed requests/events, HTTP + mock transports, SSE parsing with back-pressure and tool-call buffering. `AuthenticatedResponsesTransport` queries `AuthManager`, switches base URLs, attaches `ChatGPT-Account-Id`, retries 401s via refresh, and applies exponential backoff with jitter + `Retry-After` for API-key rate limits.
- **Tools core** (`tools/`): `FsBoundary`, `limits`, file tools, patch tools, shell/PTY, approval guard, registry + router. Tools follow the OpenAI Agents spec and use Pydantic models per `src/lincona/tools/AGENTS.md`.
- **Sessions & logging** (`sessions.py`, `logging.py`, `shutdown.py`): JSONL event writer/reader, session ID generation (`YYYYMMDDHHMM-uuid4`), per-session file logger with 5 MB truncation guard, graceful shutdown coordination.
- **CLI** (`cli.py`): entrypoint, tool subcommand runner, session helpers (`list/show/rm`), config helpers (`path/print`), and auth helpers (`auth login/logout/status`).

## Data Layout (default `~/.lincona/`)
- `config.toml` (auto-created on first run)
- `auth.json` (ChatGPT tokens + decoded claims, refreshed in place)
- `sessions/<id>/events.jsonl`
- `logs/<id>.log`

## Testing & Quality
- Unit tests cover config precedence/permissions, sessions/logging/shutdown, OpenAI client (types/transport/parsing/client), tools, and REPL behavior.
- Coverage gate enforced via `make ci`; see `tests/` for contract expectations (e.g., truncation markers, approval handling, tool schemas).

## Extensibility Notes
- Add tools by following `src/lincona/tools/AGENTS.md` and registering via `tools/__init__.py`.
- Use `MockResponsesTransport` to feed canned SSE streams in tests; avoid network I/O in unit tests.
- Respect `FsBoundary` and `ApprovalPolicy` whenever adding new mutating behaviors.
