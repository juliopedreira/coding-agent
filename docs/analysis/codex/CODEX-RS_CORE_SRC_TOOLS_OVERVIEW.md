# codex-core `tools` Module Overview

## Purpose & Flow
- Converts model tool calls into executable actions with sandboxing, approvals, telemetry, and structured responses.
- Pipeline: model `ResponseItem` → `ToolRouter` builds a `ToolCall` → `ToolRegistry` finds a `ToolHandler` → handler delegates to a `ToolRuntime` via `ToolOrchestrator` → runtime executes under sandbox/approval rules → `ToolEmitter` sends begin/end events and formatted output back to the session.

## Specs & Configuration
- `spec.rs` builds the tool list (`ToolsConfig`): chooses shell flavor (`shell`, `shell_command`, `unified_exec`, or disabled), apply_patch tool form (freeform grammar vs JSON), optional view_image, experimental tools, and web_search_request flag (feature-gated).
- `ToolsConfigParams` derived from model family + feature flags; `build_specs` (in `spec.rs`) fills a `ToolRegistryBuilder` with tool specs plus parallel-capable flags.
- Tool specs are JSON Schema (subset) or freeform grammar for apply_patch; unified exec exposes `exec_command` + `write_stdin` tools; shell tools include escalation/justification fields.

## Context & Payload Types (`context.rs`)
- `ToolInvocation`: holds `Session`, `TurnContext`, shared `TurnDiffTracker`, call_id, tool_name, and `ToolPayload`.
- `ToolPayload` variants: `Function` (JSON args), `Custom` (raw string), `LocalShell` (structured shell params), `UnifiedExec`, `Mcp` (server/tool/raw args).
- `ToolOutput`: either `Function` (content, optional content_items, success flag) or `Mcp` result; converts to protocol `ResponseInputItem` respecting custom vs function outputs.
- Telemetry preview helpers cap log size (`TELEMETRY_PREVIEW_MAX_BYTES/LINES`).

## Registry & Routing
- `registry.rs`: `ToolHandler` trait (kind Function/Mcp, match check, mutating flag, async `handle`). `ToolRegistryBuilder` registers handlers + specs; `ToolRegistry` dispatches and logs OTEL results; returns fatal vs model-visible errors.
- `router.rs`: `ToolRouter::from_config` builds specs/registry; `specs()` exposes model-facing tool list. `build_tool_call` maps `ResponseItem` to `ToolCall`, supporting MCP names via `Session::parse_mcp_tool_name`, `unified_exec`, custom tools, and `local_shell`. `dispatch_tool_call` routes to registry and wraps non-fatal errors into function/custom outputs.
- Parallel gating (`parallel.rs`): `ToolCallRuntime` runs calls concurrently; tools flagged `supports_parallel_tool_calls` share a read lock, others take a write lock (serialize). Cancellation token yields abort responses with friendly messages.

## Orchestrator & Sandboxing
- `orchestrator.rs`: central approval/sandbox driver. Steps: determine `ApprovalRequirement` (custom or default), optionally prompt user, attempt under selected sandbox (Seatbelt/Landlock/Windows or none), optionally retry without sandbox on denial if allowed and post-approval, log OTEL decisions/results. Maintains first-attempt sandbox preference and escalation-on-failure behavior.
- `sandboxing.rs`: traits and helpers.
  - `ApprovalStore` caches session-scoped approvals (`ApprovedForSession`).
  - `Approvable`: approval key, custom requirement, optional first-attempt escalation, and async approval flow (`start_approval_async`).
  - `Sandboxable`: sandbox preference and whether to retry unsandboxed on failure.
  - `ToolRuntime<Req,Out>`: trait implemented by concrete runtimes; receives `SandboxAttempt` (selected sandbox + policy) and builds exec env via `SandboxManager`.
  - `ApprovalRequirement` enum (Skip/NeedsApproval/Forbidden) with policy-derived default; `SandboxRetryData` for re-running without sandbox.

## Runtimes (`runtimes/`)
- `build_command_spec`: shared helper to validate command+env into `CommandSpec` for sandbox manager.
- `shell.rs` (`ShellRuntime`): executes tokenized commands via `execute_env`; approval key = (command, cwd, escalated); supports cached approvals, honors explicit escalated_permissions (forces no-sandbox first attempt); attaches stdout stream for live output; auto-retry without sandbox per orchestrator rules.
- `unified_exec.rs` (`UnifiedExecRuntime`): similar approvals but opens a PTY session via `UnifiedExecSessionManager`; maps sandbox denial to tool errors; exposes `write_stdin` companion tool via specs.
- `apply_patch.rs` (`ApplyPatchRuntime`): runs verified patches by re-invoking the codex binary with `CODEX_APPLY_PATCH_ARG1`; minimal env; respects prior user approval (or auto-approves if user explicitly approved upstream); sandbox-aware.

## Handlers (`handlers/`)
- `shell.rs`: two handlers—`ShellHandler` for array-based `shell` and `local_shell` calls; `ShellCommandHandler` for string-based `shell_command`. Converts params to `ExecParams`, intercepts inline `apply_patch` commands, enforces approval policy for escalations, and routes to shell runtime via orchestrator + `ToolEmitter::shell` events.
- `apply_patch.rs`: validates/repairs apply_patch input (grammar + verification), computes change set, emits patch events + turn diff via `ToolEmitter::apply_patch`; delegates to runtime when needed.
- `read_file.rs`: reads slices or indentation-aware blocks; validates absolute paths; trims long lines; supports comment-aware indentation walking.
- `list_dir.rs`: safe directory listing with depth limit and ignore rules.
- `grep_files.rs`: repo-scoped grep helper with path filters and byte limits.
- `plan.rs`: emits structured plan text (PLAN_TOOL constant) used for agent planning.
- `view_image.rs`: returns base64-encoded image bytes for local paths.
- `mcp.rs` / `mcp_resource.rs`: bridge MCP tool calls and resource reads to configured servers; surface structured MCP results.
- `unified_exec.rs` (handler): wires unified exec tools (`exec_command`, `write_stdin`) to the PTY runtime.
- `test_sync.rs`: test-only sync helper used by snapshot/integration tests.

## Events & Formatting (`events.rs`)
- `ToolEmitter` variants: Shell, ApplyPatch, UnifiedExec. Emits begin/end events (`ExecCommandBegin/End`, `PatchApplyBegin/End`, `TurnDiff`) and handles failure mapping (timeout/denied/rejected).
- Formats exec output for model consumption (structured JSON with metadata or freeform for chat), truncating with `formatted_truncate_text` according to turn truncation policy.
- Injects turn diff events when `TurnDiffTracker` has changes after apply_patch.

## Shared Helpers
- `format_exec_output_for_model_structured/freeform/str` in `mod.rs`: common truncation + metadata formatting for tool outputs; used by emitters.
- Telemetry size guards to keep preview logs small.

## Extending the Tools Layer
- Add a new tool by: defining a `ToolSpec` in `spec.rs` (plus feature/model gating), implementing a `ToolHandler`, optionally a `ToolRuntime` if sandbox/approval orchestration is needed, registering the handler in `ToolRegistryBuilder`, and updating `build_specs` if the model should advertise it.
- Ensure approvals and sandbox preferences are declared via `Approvable`/`Sandboxable`; return user-facing errors with `FunctionCallError::RespondToModel` and fatal errors with `FunctionCallError::Fatal`.
- Emit events through `ToolEmitter` so UIs/clients receive consistent begin/end notifications and formatted outputs; hook into `TurnDiffTracker` when mutating files.
