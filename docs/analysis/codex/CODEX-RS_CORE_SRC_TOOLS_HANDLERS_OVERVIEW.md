# codex-core tools/handlers Overview

## Role
Handlers translate model-declared tool calls into executable requests, perform argument parsing/validation, and delegate to runtimes via the orchestrator. They also decide mutating status (for tool gate serialization) and map errors into model-visible responses.

## Shared Traits & Registration
- Each handler implements `ToolHandler` (kind Function or Mcp; optional `is_mutating`; async `handle`).
- Registered in `handlers/mod.rs` and wired into `ToolRegistryBuilder` via `spec.rs`.
- Mutating handlers block parallel execution unless the tool is marked parallel-capable.

## Handlers
### apply_patch.rs
- Accepts `ToolPayload::Function` (JSON args) or `Custom` (freeform grammar). Re-parses and verifies patch via `codex_apply_patch::maybe_parse_apply_patch_verified`.
- If verification yields a direct `Output`, returns content immediately; if it delegates, emits patch begin events (`ToolEmitter::apply_patch`), runs `ApplyPatchRuntime` under orchestrator, then finishes with patch events + turn diff updates.
- Errors: returns model-visible messages for parse/verification failures.
- Provides two tool specs (freeform grammar and JSON) and type enum `ApplyPatchToolType` used by `ToolsConfig`.

### shell.rs
- Two handlers:
  - `ShellHandler` handles array-based `shell` and `local_shell` calls (`ToolPayload::Function` or `LocalShell`). Builds `ExecParams`, enforces approval policy for escalations, intercepts inline `apply_patch` commands (fast path), otherwise runs shell via `ShellRuntime` + `ToolOrchestrator` + `ToolEmitter::shell` events.
  - `ShellCommandHandler` handles string-based `shell_command` (model family choice). Wraps the string in user shell exec args (`bash -lc`/platform default) and delegates to the same execution path.
- `is_mutating` checks command safety with `is_known_safe_command`; unsafe or unknown treated as mutating.

### unified_exec.rs (handler)
- Bridges `exec_command` (start interactive PTY) and `write_stdin` (send input/poll output) tools to `UnifiedExecRuntime` and session manager. Supports escalating/no-sandbox per request, approvals, and uses `ToolEmitter::unified_exec` for events.

### read_file.rs
- Reads files safely; enforces absolute paths, nonzero offset/limit. Modes: `Slice` (line range) and `Indentation` (indent-aware block with optional anchor, sibling inclusion, header inclusion, max levels/lines). Trims long lines, preserves tabs via fixed width, and filters comment/blank detection helpers.

### list_dir.rs
- Directory listing with safety rails: enforces absolute root, depth limit, and path filtering to avoid traversing arbitrarily. Returns formatted listing text.

### grep_files.rs
- Workspace grep helper using ripgrep-like behavior with ignore support and byte/line caps. Takes pattern, root, and optional path filters; returns matched snippets with context.

### view_image.rs
- Reads a local image (path string), base64-encodes bytes, and returns as tool output for inline display. Rejects non-existent paths or non-files.

### plan.rs
- Generates a simple agent “plan” text block; exposed as `PLAN_TOOL` spec constant. Used when models support/require planning hints.

### mcp.rs / mcp_resource.rs
- `McpHandler`: routes MCP tool calls (server+tool+args) to configured MCP servers via `Session`; returns structured MCP results or errors.
- `McpResourceHandler`: fetches MCP resources (paths) via MCP servers; useful for agent browsing of MCP-exposed assets.

### test_sync.rs
- Test-only helper for deterministic behavior in snapshot/integration tests; syncs events as needed.

## Cross-Cutting Behaviors
- All handlers return `FunctionCallError::RespondToModel` for user-visible issues and `FunctionCallError::Fatal` for hard failures (bubbles to CLI).
- Mutating handlers trigger `tool_call_gate` serialization unless flagged parallel-capable in `ToolSpec`.
- Shell/apply_patch handlers emit begin/end events and inject `TurnDiffTracker` updates for file changes.
- Approval + sandbox are not hardcoded in handlers: they supply requirements and rely on `ToolOrchestrator` + runtimes to execute under the proper sandbox and approval policy.

## When Adding a Handler
- Add a `ToolSpec` in `spec.rs` (with feature/model gating as needed), implement `ToolHandler`, register it in `handlers/mod.rs` and `ToolRegistryBuilder`.
- Validate inputs early with clear model-facing errors; mark `is_mutating` conservatively.
- Use `ToolEmitter` for event emission; integrate `TurnDiffTracker` if files may change.
- If execution needs sandbox/approval orchestration, delegate through an appropriate `ToolRuntime` (or add a new one) via `ToolOrchestrator`.
