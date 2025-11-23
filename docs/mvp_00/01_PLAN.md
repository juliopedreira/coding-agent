# Lincona MVP_00 Delivery Plan

Each epic is self-contained and executable by an engineer without other context. Update the checkbox when completed.

## Epic 1: Project Skeleton & Tooling [x] Done
1. Initialize Poetry project for Python 3.11, package name `lincona`, CLI entrypoint `lincona` (console_script).
2. Directory layout: `src/lincona/` for code, `tests/` for unit tests, `docs/` already present, `scripts/` optional helpers.
3. Add `pyproject.toml` with dependencies: textual/rich (TUI), httpx (OpenAI), pydantic/attrs/dataclasses for configs, typing-extensions, asyncio, prompt_toolkit optional for input history if needed outside TUI. Dev deps: black, ruff, isort, mypy, pytest, pytest-cov, pytest-asyncio, freezegun, types-* stubs as needed.
4. Configure mypy strict for `src/` (disallow_any/untyped defs), relaxed for `tests/`.
5. Configure ruff (lint) and black/isort settings; ensure consistent line length (e.g., 100–120).
6. Pre-commit hooks invoking Poetry-run versions of black, ruff, isort, mypy (strict), pytest --cov with per-file ≥80% gate, plus trailing whitespace/end-of-file fixes.
7. Ensure `poetry lock` committed; document `poetry install` workflow and venv activation.
8. Add Makefile or `scripts/dev.sh` wrapper (optional) for `format`, `lint`, `typecheck`, `test` commands via Poetry for contributor convenience.

## Epic 2: Config & Persistence Layer [ ] Done
1. Config file path `~/.lincona/config.toml`; create parent dirs on first run.
2. Fields: `api_key`, `model`, `reasoning_effort`, `fs_mode`, `approval_policy`, `log_level`; env var `OPENAI_API_KEY` overrides `api_key`; CLI overrides config.
3. Provide config load/save helpers with precedence: CLI flags > env > config file > hardcoded defaults.
4. Session storage under `~/.lincona/sessions/<session_id>.jsonl`; generate unique IDs (timestamp + random suffix).
5. Logging directory `~/.lincona/logs/`; create per-session plaintext log file.
6. JSONL event schema covering: system metadata, user messages, model messages, tool calls/outputs, slash-command events, truncation notices.
7. Expose helpers to list/resume/delete sessions for TUI and CLI `sessions` commands.
8. Graceful shutdown writes pending session file and closes PTYs.

## Epic 3: OpenAI Responses Client [x] Done
1. Implement client wrapper around OpenAI Responses API using httpx (async), supporting streaming deltas and tool call callbacks.
2. Parameters: `model` (user-selectable), `reasoning_effort` (pass-through), `tools` advertisement (JSON + freeform apply_patch as two entries), `messages` with history.
3. Provide interface to submit a turn, stream tokens and tool-call messages to the conversation manager.
4. Error handling: timeouts, rate limits, invalid API key; surface user-friendly errors to UI/logs.
5. Pluggable transport: real HTTP and a mockable in-memory client for unit tests; toggle via config/flag for E2E.
6. Ensure back-pressure/flow control so TUI can render streams smoothly.

## Epic 4: Tooling Core & Filesystem Boundaries [ ] Done
1. Implement `fs_mode` enforcement:
   - `restricted`: root = process cwd (or detected git root of cwd); reject paths escaping root; normalize relative/absolute inputs.
   - `unrestricted`: allow absolute paths.
2. Tools (model-facing):
   - `list_dir`: depth-limited listing, offset/limit, formats one entry per line.
   - `read_file`: line slice and indentation modes; offset/limit validation; trims overly long lines.
   - `grep_files`: regex search with include globs and limits; pure-Python fallback (no ripgrep dependency).
   - `apply_patch_json`: accept unified diff string; verify and apply atomically; fail on malformed or paths outside allowed root.
   - `apply_patch_freeform`: parse Codex-style envelope; reuse verification/apply logic.
   - `shell`: run command string via user shell; respect workdir (validated against fs_mode); enforce timeout.
   - `exec_command` + `write_stdin`: PTY-backed long-lived session; track session IDs; enforce fs_mode on initial workdir.
3. Output caps: truncate stdout/stderr beyond 8KB or 200 lines with “[truncated]” marker returned to model/UI.
4. Approval policy (no sandbox): honor `approval_policy` state but default to `never`; structure hooks so future sandboxing can plug in.
5. Emit structured tool-call events for persistence and UI side pane.

## Epic 5: Conversation & Session Manager [ ] Done
1. Manage multi-turn sessions: maintain history, current model, reasoning_effort, fs_mode, approval_policy, session id.
2. Apply slash commands: `/newsession`, `/model <id>`, `/reasoning <level>`, `/approvals <never|on-request|always>`, `/fsmode <restricted|unrestricted>`, `/help`, `/quit`.
3. Start new session resets history and state; persists previous session file before switching.
4. Provide API for TUI to fetch current state and apply commands, with validation and user feedback strings.
5. Integrate with OpenAI client to assemble request messages and tools list per current state.

## Epic 6: TUI Frontend (Textual/Rich) [ ] Done
1. Layout: main chat pane (streamed tokens), side pane listing tool calls with status (pending/running/success/fail), bottom input box with multiline and history (↑/↓), optional Ctrl+R search.
2. Status bar showing session id, model, reasoning_effort, fs_mode, approval_policy.
3. Session picker view to list/resume sessions or start new; accessible at startup or via command.
4. Render slash command help overlay; show errors inline without crashing UI.
5. Stream handling: append tokens as they arrive; when tool calls occur, show call entry and update with output/truncation markers.
6. Keyboard shortcuts: Enter send, Shift+Enter newline, Esc to blur, Ctrl+C to quit gracefully (persist session).
7. Clear separation: UI components call backend services; no business logic in widgets.

## Epic 7: Standalone Tool CLIs [ ] Done
1. `lincona tool <tool-name>` subcommand for each tool: list_dir, read_file, grep_files, apply_patch, shell, exec_command, write_stdin.
2. Accept argparse-style flags and `--json` payload alternative; validate mutual exclusivity and required fields.
3. Enforce fs_mode rules (inherits from config/flags) and print structured outputs (human by default, optional `--output json`).
4. Return proper exit codes; document usage in `--help`.

## Epic 8: Logging & Telemetry [ ] Done
1. Plaintext per-session log in `~/.lincona/logs/<id>.log` with timestamps, level, component; rotate/truncate to sane size.
2. JSONL transcript in `sessions/<id>.jsonl` capturing chat, tool calls, outputs, slash commands, errors, truncation notices.
3. Logging module initializes once; avoids duplicate handlers; no noisy stdout from libraries.
4. Provide log level control via config/flag; default `info`.

## Epic 9: Packaging & Distribution [ ] Done
1. Poetry build artifacts; ensure console_script entrypoint.
2. Docker multi-stage build:
   - Stage 1: install Poetry, copy project, `poetry install --only main` (or export requirements).
   - Stage 2: slim runtime with only needed env vars; default CMD `["lincona", "tui"]`.
3. Document image usage and how to pass OPENAI_API_KEY and mount project workspace.
4. Verify image can run TUI and standalone tools.

## Epic 10: Testing & Quality Gates [ ] Done
1. Unit tests with mocks: OpenAI client, filesystem, subprocess/PTY; no network or real writes.
2. Pytest-cov enforcing ≥80% coverage per source file (fail build otherwise).
3. Tests for fs_mode enforcement, slash command parsing, tool arg validation, truncation behavior, logging/persistence outputs.
4. Standalone tool CLI tests (argparse) including `--json`.
5. Optional/manual E2E: flag to use mock OpenAI vs real; script checklist to run TUI, perform list/read/apply_patch/shell/exec.
6. Pre-commit CI path runs: lint, format, typecheck, tests with coverage.
