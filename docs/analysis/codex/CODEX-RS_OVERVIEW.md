# codex-rs Overview

## Purpose
The Rust implementation of the Codex CLI and related tooling. It provides a native, sandbox-aware coding agent with interactive TUI, non-interactive automation, IDE-facing app server, and policy/sandbox utilities. The workspace is the maintained path forward; the legacy TypeScript CLI simply wraps the Rust binary.

## Workspace Shape
- Cargo workspace (edition 2024) under `codex-rs/`, crates prefixed `codex-…` in Cargo.toml.
- Binaries exposed via the `cli` crate (`codex`), with subcommands wiring other crates.
- Shared dependencies pinned in `[workspace.dependencies]`; utilities are broken into narrow crates to keep compile times manageable.

### Primary Crates
- `core/` (`codex-core`): conversation engine, tool execution, sandbox selection, execpolicy hooks, auth/config loaders, conversation history, rollouts, MCP client plumbing, OpenAI/local provider selection, response parsing, turn diff tracking.
- `cli/`: user-facing multitool. Dispatches TUI, exec, login/logout, app-server, sandbox runners, execpolicy checks, completion generation, session resume, cloud tasks, and internal helpers (responses API proxy, stdio-to-uds).
- `tui/`: Ratatui fullscreen client; snapshot-tested rendering. Styling helpers via Stylize; wrapping via `textwrap` and custom helpers.
- `exec/`: non-interactive/CI runner (`codex exec`). Streams JSONL events or human-readable progress, enforces stdout cleanliness, and stitches together config/auth/approval/sandbox handling.
- `app-server/` (+ `app-server-protocol`, `app-server-test-client`): stdio JSON-RPC server backing IDE extensions. Can emit TS or JSON Schema for the protocol.
- `execpolicy/` (+ `execpolicy-legacy`): Starlark prefix-rule evaluator returning allow/prompt/forbidden. Used both standalone and from `core` when deciding whether to run tools.
- `protocol/`: shared wire types and config enums used across crates (and re-exported from `core`).
- `chatgpt/`, `backend-client/`: clients for OpenAI backend services and API-facing calls.
- Local provider support: `ollama/`, `lmstudio/` plus helper crates like `utils/image` for encoding.
- Sandbox and hardening: `linux-sandbox`, `windows-sandbox-rs`, `process-hardening`, `seatbelt` (policies under `core/sandboxing`), `landlock` helpers.
- Utilities: `apply-patch`, `file-search`, `ansi-escape`, `async-utils`, `keyring-store`, `otel`, `responses-api-proxy`, and `utils/*` (git, cache, pty, json-to-toml, readiness, string, image, cache, pty, etc.).
- Test support: `core/tests/common` (core_test_support), `mcp-server/tests/common` (mcp_test_support), `app-server/tests/common` (app_test_support).

## Binaries & Subcommands (via `codex`)
- No subcommand ⇒ TUI (`codex-tui`).
- `exec` ⇒ headless automation; supports JSONL output, images, output schemas.
- `login` / `logout` ⇒ credential flows (ChatGPT, device code, API key).
- `mcp`, `mcp-server` ⇒ manage or run the Codex MCP server.
- `app-server` ⇒ IDE/stdio server; can generate protocol schemas.
- `sandbox macos|linux|windows` ⇒ run arbitrary commands inside Codex-provided sandboxes.
- `execpolicy check` ⇒ evaluate policy files against a command.
- `apply` ⇒ apply latest Codex-generated diff as `git apply`.
- Hidden/internal: responses API proxy, stdio-to-uds relay, cloud tasks preview.

## Core Runtime Flow
1. CLI parses flags and resolves config profile (`config.toml` under `~/.codex`), plus CLI overrides.
2. Auth manager ensures credentials (ChatGPT login or API key) and enforces restrictions.
3. Conversation manager sets up thread/turn, loads history, and picks model/provider (OpenAI, Ollama, LM Studio, etc.).
4. Approval & sandbox policy chosen (read-only / workspace-write / danger-full-access); execpolicy rules gate shell/apply-patch/file-search calls.
5. Tool calls execute through sandbox wrappers; outputs are streamed as structured events.
6. Renderers (TUI or exec human/JSONL) consume events; rollouts persist under `~/.codex/sessions` (archived sessions supported).

## Sandbox & Hardening
- macOS: Seatbelt profiles (`core/sandboxing/seatbelt_*.sbpl`).
- Linux: Landlock + seccomp (`linux-sandbox`), plus optional `--sandbox` CLI selection.
- Windows: restricted token (`windows-sandbox-rs`).
- Additional hardening in `process-hardening`; environment flags prevent recursive sandboxing in tests.

## Execpolicy
- Starlark `prefix_rule(pattern=[...], decision, match?, not_match?)` language.
- Effective decision is strictest of matching prefixes (forbidden > prompt > allow).
- CLI `codex execpolicy check --policy file.codexpolicy --pretty git status` outputs structured JSON.

## MCP Support
- MCP client: `core` can connect to configured servers at startup.
- MCP server: `mcp-server` crate exposes Codex as an MCP tool; `cli` exposes `mcp-server` subcommand.
- Types live in `mcp-types`; test helpers in `mcp-server/tests/common`.

## Data & Config
- Config file: `~/.codex/config.toml`; CLI overrides for sandbox, approval, model, cwd, etc.
- Sessions/rollouts stored under `~/.codex/sessions`; archived sessions in `~/.codex/sessions/archived`.
- Environment helpers: `config_loader`, `config` modules; `project_doc` surfaces repo docs to the agent.

## Build & Testing Workflow
- Formatting: `just fmt` (no approval needed per AGENTS.md).
- Lint fixes: `just fix -p <crate>` after code changes; run full `just fix` only if shared crates touched.
- Tests: `cargo test -p <crate>` for modified crates; if `common`, `core`, or `protocol` change, also run `cargo test --all-features`.
- TUI snapshots: `cargo test -p codex-tui`; inspect `.snap.new`, accept via `cargo insta accept -p codex-tui` when intentional.

## Coding Conventions & Clippy Expectations
- Inline `format!` arguments; collapse nested `if`; prefer method references over closures.
- Avoid unsigned integers; prefer whole-object assertions in tests; use `pretty_assertions::assert_eq`.
- Use Ratatui Stylize helpers (`.dim()`, `.red()`, etc.) and `textwrap`/wrapping helpers for UI text.
- Do not touch sandbox env var constants (`CODEX_SANDBOX_*` guards used to skip unsupported tests).

## When Extending codex-rs
- Update docs in `docs/` if you add or change user-facing behavior or APIs.
- Prefer narrow crates/features to keep compile times low.
- Ensure new tools respect execpolicy and sandbox selection; stream structured events for UI/automation consumers.
- Keep stdout clean in library code (clippy denies print to stdout/stderr in many crates); use tracing/TUI renderers instead.
