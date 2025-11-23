# Codex Codebase Overview

## What Codex Is
- Local-first coding agent CLI with sandboxed shell execution and approval modes.
- Primary implementation in Rust (`codex-rs`); small Node wrapper publishes the binary via npm/Homebrew.
- Exposes JSON-RPC app server for IDEs, a headless `codex exec` for automation, and a Ratatui-based TUI for interactive use.

## Repository Layout (root)
- `codex-rs/` — Rust workspace containing the agent engine and supporting binaries.
- `codex-cli/` — Node launcher that selects the bundled native binary for the host and forwards signals/env.
- `sdk/typescript/` — TypeScript SDK that spawns the CLI and streams JSONL events.
- `shell-tool-mcp/` — npm package bundling the shell MCP server plus patched Bash/exec wrapper.
- `docs/` — user docs (getting started, config, sandbox, auth, FAQ) shared across implementations.

## Rust Workspace Highlights (codex-rs/)
- Core logic: `core/` (`codex-core`) handles conversations, tool calls, config/auth, sandbox selection (Seatbelt/Landlock/Windows), exec-policy checks, and MCP client/server hooks.
- Entrypoint: `cli/` wires the `codex` multitool subcommands (TUI, exec, login, app-server, sandbox runners, execpolicy, completions).
- Interactive UI: `tui/` provides the Ratatui fullscreen interface; heavy on snapshot tests.
- Non-interactive: `exec/` implements `codex exec` for CI/automation with human or JSONL output.
- IDE bridge: `app-server/` (+ `app-server-protocol`, `app-server-test-client`) runs a stdio JSON-RPC server; can emit TS/JSON schemas of the message shapes.
- Policy engine: `execpolicy/` (+ `execpolicy-legacy`) evaluates Starlark prefix rules to allow/prompt/forbid commands.
- Model providers: `chatgpt`, `ollama`, `lmstudio`, `backend-client`, `protocol` handle model/backend integrations and protocol types.
- Sandboxing/hardening: `linux-sandbox`, `windows-sandbox-rs`, `process-hardening`, plus Seatbelt/Landlock helpers under `core/sandboxing`.
- Utilities: `apply-patch`, `file-search`, `ansi-escape`, `async-utils`, `keyring-store`, `otel`, `responses-api-proxy`, and `utils/*` (git, cache, pty, image, json-to-toml, readiness, string).

## JavaScript/TypeScript Packages
- `codex-cli`: npm/global entry that ships the Rust binary in `vendor/` and launches it with correct target triple and PATH tweaks.
- `sdk/typescript`: Provides `Codex` and `Thread` abstractions, supports structured output schemas, image inputs, and streamed events by spawning the CLI.
- `shell-tool-mcp`: `npx @openai/codex-shell-tool-mcp` launcher for the shell MCP server; includes patched Bash honoring `BASH_EXEC_WRAPPER` and execve wrapper binaries.

## Typical Runtime Flow
1) User runs `codex` (TUI or exec). CLI parses flags, loads config/auth, resolves model provider (OpenAI or local OSS via Ollama/LM Studio).
2) `core` builds a conversation, applies sandbox/approval policy, and streams model events.
3) Tool calls (shell, apply-patch, file search) are executed inside the selected sandbox and gated by execpolicy.
4) Outputs are rendered by the TUI or emitted as JSONL/human text; sessions/threads/turns persist under `~/.codex`.

## Build & Test Pointers (Rust)
- Formatting: `just fmt` (workspace-aware).
- Lint fixes: `just fix -p <crate>` preferred; run full `just fix` only if shared crates changed.
- Tests: run `cargo test -p <crate>` for touched crates; if common/core/protocol changed, run `cargo test --all-features`.
- Snapshots (TUI): `cargo test -p codex-tui`, inspect `.snap.new`, accept via `cargo insta accept -p codex-tui` when intentional.

## Useful Docs
- Quickstart & CLI usage: `docs/getting-started.md`
- Configuration reference: `docs/config.md`
- Sandbox details: `docs/sandbox.md`
- Auth options: `docs/authentication.md`
- Execpolicy language: `codex-rs/execpolicy/README.md`
- App server protocol: `codex-rs/app-server/README.md`
