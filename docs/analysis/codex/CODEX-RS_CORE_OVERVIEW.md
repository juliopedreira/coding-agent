# codex-core Overview

## Purpose
`codex-core` is the heart of the Rust Codex CLI. It owns conversation management, tool execution, provider/model selection, sandbox/approval enforcement, history persistence, and the structured event stream consumed by the TUI, `codex exec`, and the app-server. The crate is library-first (no stdout prints; clippy forbids it) and exposes types used across the workspace.

## Responsibilities (high level)
- Parse and normalize user input into internal commands/prompts.
- Load configuration/auth, pick the model provider (OpenAI, Ollama, LM Studio, etc.).
- Orchestrate turns: maintain conversation state/history, assemble prompts, stream model output, map it to structured events.
- Execute tools (shell, apply-patch, file search, MCP tools) with sandbox + execpolicy gating.
- Track diffs and filesystem changes for review and apply flows.
- Persist rollouts/sessions and surface project docs as context.
- Initialize observability (tracing/OpenTelemetry).

## Key Modules
- `config` & `config_loader`: parse `~/.codex/config.toml`, apply CLI overrides, resolve sandbox/approval defaults, MCP servers, provider settings; `find_codex_home` and profile support.
- `auth`: manages auth state (ChatGPT login, API key); enforces login restrictions and surfaces `AuthManager`.
- `features`: feature flag registry (`is_known_feature_key`) shared across CLI.
- `model_provider_info`, `openai_model_info`, `model_family`: provider metadata, default ports, model capabilities, and helpers to construct provider configs; includes OSS provider constructors for Ollama/LM Studio.
- `client` / `client_common` / `default_client`: abstraction over LLM providers; exposes `ModelClient`, prompt builders, streaming `ResponseEvent`s, `ResponseStream`, retry/backoff logic, and default originator tagging.
- `codex_conversation`, `conversation_manager`, `codex.rs`: orchestrate a turn—build system/user/tool messages, load history, wire in project docs/custom prompts, manage interrupts and approvals, and emit protocol events.
- `message_history`, `truncate`, `compact` / `compact_remote`: maintain/history trimming and token-aware compaction of past turns; `content_items_to_text` helpers.
- `tools`: registry and dispatch of tool calls (shell commands, apply-patch, file search, MCP tool calls, custom function tools).
- `shell`, `bash`, `powershell`, `exec_env`, `spawn`, `user_shell_command`, `command_safety`: platform-aware shell execution, environment assembly, safe command detection (`is_safe_command`), sandbox negotiation, stdio handling.
- `sandboxing`, `seatbelt`, `landlock`, `safety`: choose sandbox backend per platform; seatbelt SBPL policies (macOS), Landlock/seccomp wiring (Linux), Windows restricted token toggles; helpers `get_platform_sandbox` / `set_windows_sandbox_enabled`.
- `exec_policy`: bridges to execpolicy engine; determines allow/prompt/forbid for candidate commands before execution.
- `apply_patch`: safe patch application; exported `CODEX_APPLY_PATCH_ARG1` for upstreams.
- `git_info`: gather repo metadata (root path, branch, dirty state) for prompt/context.
- `project_doc`: reads repo docs (e.g., AGENTS.md) to feed into system context.
- `custom_prompts`, `user_instructions`: load user/agent instructions and project-specific prompts.
- `environment_context`: captures cwd, repo info, and platform details for prompts and telemetry.
- `response_processing`, `event_mapping`: map raw model deltas to protocol events/items; handle function/tool call plumbing.
- `turn_diff_tracker`: tracks file diffs across a turn to summarize/apply changes.
- `tasks`: task-specific helpers (e.g., review formatting in `review_format`).
- `mcp`, `mcp_connection_manager`, `mcp_tool_call`: MCP client wiring; connects to configured MCP servers and routes tool invocations.
- `otel_init`: OpenTelemetry/tracing setup (stdout-silent); integrates with otel appender layer.
- `state`, `context_manager`, `flags`, `token_data`: misc session state, CLI flag parsing helpers, token accounting utilities.
- `terminal`: terminal capabilities/color detection used by TUI/exec renderers.
- `error`: shared error types; thin anyhow wrappers for ergonomic propagation.

## Data & Event Flow (per turn)
1. CLI hands prompt + config overrides to `ConversationManager`.
2. `config_loader` resolves profile + overrides; `auth` ensures credentials; `environment_context` captures cwd/repo/platform.
3. Provider selection (`model_provider_info`, `resolve_oss_provider`) sets model + client; `client` begins streaming.
4. `codex_conversation` builds the message list (system, history, user, project docs, custom prompts) and registers available tools.
5. Streamed deltas are parsed (`response_processing` → `event_mapping`) into protocol events; tool calls are executed via `tools` with sandbox + execpolicy enforcement.
6. Outputs/events feed UIs (TUI/exec/app-server); `turn_diff_tracker` snapshots file changes; history and rollouts are persisted.

## Sandbox & Approval Enforcement
- Sandbox chosen via CLI/config (`sandbox_mode`: read-only, workspace-write, danger-full-access).
- Platform adapters: Seatbelt (macOS SBPL), Landlock/seccomp (Linux), Windows restricted token.
- Execpolicy: before executing shell-like tools, `exec_policy` consults Starlark rules (allow/prompt/forbid).
- Safety flags (`CODEX_SANDBOX_*`) prevent recursive sandboxing in tests; do not modify these constants.

## Extensibility Guidelines
- New tools: register in `tools`, respect execpolicy + sandbox, and emit structured events.
- Prompt changes: keep history compaction/truncation in mind; ensure token limits via `truncate`/`compact`.
- Provider additions: extend `model_provider_info` and plumb through `client`/`default_client`.
- Observability: use `tracing`; never print to stdout/stderr inside the library.
- Tests: prefer whole-object assertions and `pretty_assertions::assert_eq`; use test support crates for SSE/mocking; skip sandbox-heavy tests when `CODEX_SANDBOX_*` envs are set.

## Files to Know (paths relative to `codex-rs/core/src`)
- `lib.rs`: public surface/re-exports; clippy denies stdout/stderr prints here.
- `codex.rs`, `codex_conversation.rs`, `conversation_manager.rs`: main orchestration.
- `config/`, `config_loader/`: config parsing and profile resolution.
- `tools/`, `shell.rs`, `exec_env.rs`, `command_safety.rs`: tool execution pipeline.
- `sandboxing/`, `seatbelt*.sbpl`, `landlock.rs`, `safety.rs`: sandbox selection and policies.
- `model_provider_info.rs`, `openai_model_info.rs`: provider metadata.
- `response_processing.rs`, `event_mapping.rs`: delta-to-event mapping.
- `turn_diff_tracker.rs`: change tracking.
- `project_doc.rs`, `custom_prompts.rs`, `user_instructions.rs`: context sources.
- `otel_init.rs`: tracing/OTel bootstrap.

## Testing & CI Expectations
- Core tests live alongside modules plus shared helpers in `core/tests/common` (exposed as `core_test_support`).
- Use `cargo test -p codex-core`; if core/common/protocol are touched, run `cargo test --all-features` per repo policy.
- Formatting/lints handled at workspace level via `just fmt` and `just fix -p codex-core` when code changes.
