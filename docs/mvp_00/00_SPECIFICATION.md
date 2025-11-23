# Lincona MVP Specification (MVP_00)

Goal: ship a Linux-only interactive coding agent CLI, inspired by Codex, using Python 3.11 with Poetry. The MVP focuses on a TUI chat experience backed by OpenAI Responses API tools, minimal safety gates (no sandbox), and strong developer ergonomics (typing, linting, tests, coverage, pre-commit, Docker).

## In Scope
- Interactive TUI chat experience (Textual/Rich) with multi-turn sessions, resumable from disk.
- Tooling exposed to the model: `list_dir`, `read_file`, `grep_files`, `apply_patch` (JSON + freeform envelope), `shell` (string command), `exec/pty` (long-lived command session).
- User slash-commands during a session: `/newsession`, `/model <id>`, `/reasoning <level>`, `/approvals <policy>`, `/fsmode <restricted|unrestricted>`, `/help`, `/quit`.
- FS boundary modes: `restricted` (only cwd subtree) and `unrestricted`; user can switch live.
- Approval policy default: `never` (trusted user); user can switch via slash command.
- Persistence: config + sessions.
  - `~/.lincona/config.toml` for defaults (api_key, model, reasoning_effort, fs_mode, approval_policy, log_level).
  - `~/.lincona/sessions/<id>.jsonl` for transcripts/events (JSONL).
  - `~/.lincona/logs/<id>.log` plaintext run log.
- Provider: OpenAI Responses API; user-selectable model + reasoning effort per session; streaming responses.
- Standalone console tools (non-chat) for each capability with argparse-style flags and optional `--json` payloads.
- Packaging: Poetry-managed project; CLI entrypoint `lincona`; Docker image build; venv-first workflow.
- Quality gates: mypy (strict for `src/`, relaxed for `tests/`), ruff/black/isort, pytest with per-file coverage ≥80% (source files), pre-commit running Poetry commands, unit tests mocked (no network/filesystem writes), optional manual E2E with real or mocked OpenAI.

## Out of Scope (MVP)
- Sandboxing, execpolicy, OS-level hardening.
- Windows/macOS support.
- Authentication flows beyond static API key env/config.
- Advanced planning/review modes, app-server/JSON-RPC, MCP, web search.
- Cloud packaging or Homebrew/npx distribution.

## Architecture Overview
- **Frontend (TUI)**: Textual/Rich app renders:
  - Chat pane with streamed model and tool output.
  - Side pane with tool call statuses.
  - Input box (multiline, history, shortcuts ↑/↓, Ctrl+R optional).
  - Session picker (list + resume/start new).
  - Slash command handler for runtime controls.
- **Agent Core**:
  - Conversation/session manager (load/save history, generate session IDs, route slash commands, handle fs_mode/approval/model/reasoning switches).
  - Tool router + specs for Responses API (JSON tools + freeform apply_patch).
  - Tool executors: filesystem readers, patch applier (verified envelope), shell runner, PTY manager.
  - OpenAI client wrapper for Responses API (streaming, tool callbacks, model/effort selection).
  - Event/log emitter (JSONL + human log).
- **CLI Entry (`lincona`)**:
  - `lincona tui` (default): launch TUI chat.
  - `lincona tool <tool-name> [args|--json PAYLOAD]`: invoke tools standalone.
  - `lincona sessions list|show|rm <id>` (lightweight helpers).
  - `lincona config path/print` (optional convenience).
- **Data directories** (base `~/.lincona/`):
  - `config.toml`
  - `sessions/<id>.jsonl`
  - `logs/<id>.log`
  - `cache/` (future use; may be empty in MVP)

## Tools (Model-Facing Specs)
Expose via OpenAI Responses tools:
- `list_dir` (function): params `path` (abs or relative to session root), `depth` (default 2), `limit`, `offset`.
- `read_file` (function): params `path`, optional `offset`, `limit` (lines), `mode` (`slice|indentation`), indentation options.
- `grep_files` (function): params `pattern`, optional `path` root, `include` globs, `limit`.
- `apply_patch_json` (function): `patch` string containing unified diff (verified).
- `apply_patch_freeform` (custom/freeform tool): Codex-style envelope `*** Begin Patch ... *** End Patch`.
- `shell` (function): `command` string, optional `workdir`, `timeout_ms`.
- `exec_command` (function): `cmd` string, optional `workdir`, `yield_time_ms`, `max_output_tokens`.
- `write_stdin` (function): `session_id`, `chars`, optional `yield_time_ms`, `max_output_tokens`.

Model advertisement: both JSON and freeform apply_patch appear as separate tools.

## Tool Execution Rules
- FS access respects current `fs_mode`:
  - `restricted`: resolve root to process cwd (or detected git root of cwd); deny escapes.
  - `unrestricted`: allow absolute paths.
- Mutating tools (`apply_patch`, `shell`, `exec_command/write_stdin`) allowed without approval by default; no sandbox in MVP.
- Timeouts: sensible defaults (e.g., shell 60s) with per-call override.
- Output truncation: cap large outputs (e.g., 8KB or 200 lines) with clear “[truncated]” marker.
- PTY sessions tracked by ID; auto-terminated on session end.

## Slash Commands (during chat)
- `/newsession` – end current, start fresh (new session id, clears history).
- `/model <id>` – switch model for subsequent turns.
- `/reasoning <level>` – set reasoning effort (pass-through to Responses API).
- `/approvals <never|on-request|always>` – set approval policy (stored in session state; default `never`).
- `/fsmode <restricted|unrestricted>` – toggle filesystem boundary.
- `/help` – show built-ins; `/quit` – exit TUI.

## Config (`~/.lincona/config.toml`)
```toml
api_key = "..."               # or use env OPENAI_API_KEY
model = "gpt-4.1"             # default
reasoning_effort = "medium"   # per Responses API
fs_mode = "restricted"        # or unrestricted
approval_policy = "never"     # never|on-request|always
log_level = "info"
```
CLI flags override config; slash commands override in-session; latest session state persists in session file, not config.

## Persistence & Logging
- Session transcript: JSONL events (chat messages, tool calls, outputs, slash commands) stored at end of session under `sessions/<id>.jsonl`.
- Plaintext log per session in `logs/<id>.log` (info/debug, truncated on rotation limit).
- Resume flow: TUI lists sessions; user can resume; restores conversation history and state (model, reasoning, fs_mode, approval_policy).

## Packaging & Tooling
- Python 3.11; Poetry-managed `pyproject.toml`.
- CLI entrypoint: `lincona`.
- Dev tools via Poetry + pre-commit: black, ruff, isort, mypy (strict for `src/`; allow `ignore_missing_imports`/less strict in tests), pytest, coverage (fail if any source file <80%).
- Pre-commit runs Poetry commands to ensure env consistency.
- Docker: multi-stage image (builder installs Poetry deps; runtime slim with entrypoint `lincona tui` by default; allow `CMD ["lincona", "..."]` override).

## Testing Strategy
- Unit tests: mock OpenAI client, filesystem, and subprocesses; no real network or disk writes.
- Coverage: enforce ≥80% per source file (pytest-cov).
- E2E (manual/flagged): launch TUI, run `list_dir`, `read_file`, `apply_patch`, `shell`, `exec_command/write_stdin`; support toggling between mocked OpenAI server and real OpenAI via flag/config.
- Standalone tool CLIs tested with argparse invocations (both positional flags and `--json` payload).

## UX Notes
- Clear separation of UI (Textual/Rich) from backend core (pure Python services).
- Streamed tokens in chat pane; tool call status in side pane; concise error messaging.
- Show current model/reasoning/fs_mode/approval_policy in status bar.
- Truncation indicators and path rooting hints when in restricted mode.

## Non-Functional Requirements
- Strict typing in `src/` (`mypy --strict`); tests may relax.
- No stdout/stderr noise from libraries; logging via standard logging module.
- Handle Ctrl+C gracefully (clean PTYs, flush logs, write session file).
- Performance: handle medium repos; ripgrep not required (can use Python glob + regex in MVP).

## Migration/Future Hooks (post-MVP)
- Sandbox + execpolicy integration.
- Mac/Windows support.
- MCP/app-server/JSON-RPC for IDEs.
- Web search tool; auth flows; cloud packaging.

## Acceptance Criteria (MVP_00)
- Running `lincona tui` on Linux with OPENAI_API_KEY set starts the TUI, streams model output, and allows tool calls for the listed tool set.
- Slash commands work and reflect in status bar and behavior.
- FS modes enforced as specified; unrestricted allows abs paths; restricted blocks escapes.
- Sessions and logs written to `~/.lincona/`; sessions can be resumed with history intact.
- Standalone tool commands execute and accept both CLI flags and `--json` input.
- Lint/format/type/coverage gates enforced via pre-commit/CI; Docker image builds successfully.
