# shell & shell_command handlers — Detailed Specification

Source: `codex-rs/core/src/tools/handlers/shell.rs`

Purpose
- Execute shell commands requested by the model, with approval/sandbox gating, telemetry events, apply_patch interception, and safe formatting of outputs.
- Two handlers:
  - `ShellHandler` for array-based `shell` and `local_shell` calls.
  - `ShellCommandHandler` for string-based `shell_command` calls (wraps in user shell exec args).

Accepted Payloads
- `ShellHandler`: `ToolPayload::Function { arguments: String }` → JSON `ShellToolCallParams`; `ToolPayload::LocalShell { params: ShellToolCallParams }`.
- `ShellCommandHandler`: `ToolPayload::Function { arguments: String }` → JSON `ShellCommandToolCallParams` (single command string, workdir, timeout_ms, escalation flags).

Output
- On success: `ToolOutput::Function { content, content_items: None, success: Some(true) }`.
- On non-zero exit/denial/timeout: returns `FunctionCallError::RespondToModel(formatted_output)` (formatted/truncated text).
- Fatal parsing/type errors: `FunctionCallError::RespondToModel` or `Fatal` depending on severity.

Core Behaviour (shared)
1) Parse params from JSON; resolve working directory via `TurnContext::resolve_path`.
2) Build `ExecParams` (command Vec<String>, cwd, timeout, env from `create_env`, escalation flags, justification).
3) Approval policy guard: if params request `with_escalated_permissions == true` while approval policy is not `OnRequest`, respond with error (model-visible) and abort.
4) Inline apply_patch interception: `codex_apply_patch::maybe_parse_apply_patch_verified(command, cwd)` — if patch detected, delegate to apply_patch flow (same as apply_patch handler) including events and orchestrator with ApplyPatchRuntime.
5) Otherwise, emit ToolEmitter::shell begin event (source = Agent, freeform flag depends on handler: shell_command uses freeform=true so model sees freeform output formatting).
6) Build ShellRequest with approval requirement from `create_approval_requirement_for_command` (execpolicy + sandbox policy + escalation flag) and run through `ToolOrchestrator` + `ShellRuntime`.
7) Finish emitter, mapping success/timeout/denial/rejection to model outputs via `ToolEmitter::finish`.

Differences
- `ShellHandler::to_exec_params`: uses passed command Vec<String>; `with_escalated_permissions`/justification are forwarded.
- `ShellCommandHandler::to_exec_params`: wraps command string using user shell (`Shell::derive_exec_args(command, use_login_shell=true)`); marks handler as Function kind only.
- `is_mutating`: ShellHandler checks command safety via `is_known_safe_command`; LocalShell params considered mutating if not known-safe. ShellCommandHandler relies on default (mutating not overridden).

Pseudocode (ShellHandler)
```
handle_shell(invocation):
  params = parse ShellToolCallParams from payload
  exec = build ExecParams(params, turn)
  if exec.with_escalated_permissions && approval_policy != OnRequest:
      error RespondToModel("approval policy is ...")
  if maybe_parse_apply_patch_verified(exec.command, exec.cwd) -> Body(changes):
      apply_patch::apply_patch or delegate via ApplyPatchRuntime (with events)
      return ToolOutput(Function, content)
  emitter = ToolEmitter::shell(command, cwd, Agent, freeform=false)
  emitter.begin(ctx)
  req = ShellRequest{command, cwd, timeout_ms, env, with_escalated_permissions, justification, approval_requirement=create_approval_requirement_for_command(...)}
  out = Orchestrator.run(ShellRuntime, req,...)
  content = emitter.finish(ctx, out)?
  return ToolOutput(Function, content, success=true)
```

Pseudocode (ShellCommandHandler)
```
handle_shell_command(invocation):
  params = parse ShellCommandToolCallParams
  exec = wrap via session.user_shell().derive_exec_args(params.command, use_login_shell=true)
  delegate to ShellHandler::run_exec_like(... freeform=true)
```

Events
- Emits `ExecCommandBegin/End` via ToolEmitter (includes parsed command tokens, cwd, source, interaction input=None).
- On apply_patch intercept, emits `PatchApplyBegin/End` and `TurnDiff` if changes recorded.

Call Graph
- Handler → maybe apply_patch interception → (apply_patch::apply_patch or ApplyPatchRuntime)
- Else: ToolEmitter::shell.begin → ToolOrchestrator::run(ShellRuntime) → ToolEmitter::finish → ToolOutput

Edge Cases
- Empty/invalid JSON args → RespondToModel parse error.
- Missing LocalShell call_id (only for LocalShell payload) yields `FunctionCallError::MissingLocalShellCallId` upstream in router.
- Sandbox denial/timeouts surfaced as model-visible formatted output via emitter.

Reimplementation Notes
- Preserve approval guard logic for escalated permissions.
- Respect `create_approval_requirement_for_command` result (execpolicy + sandbox + escalation).
- Use same output formatting: `format_exec_output_for_model_structured` unless freeform=true (shell_command) → freeform formatter.
- Keep telemetry/log payload truncation unchanged (handled in context/format helpers).

## Input/Output Examples
- **shell success (array args)**  
  Payload: `{"command":["echo","hi"],"workdir":"/repo","timeout_ms":5000}`  
  Output: ToolOutput content contains `Exit code: 0` and `hi`; `success: Some(true)`.

- **shell non-zero exit**  
  Payload: `{"command":["false"],"workdir":"/repo"}`  
  Output: `FunctionCallError::RespondToModel` with formatted exec output (exit code 1, stderr), no success flag.

- **shell_command success (string)**  
  Payload: `{"command":"ls -1","workdir":"/repo"}`  
  Output: ToolOutput freeform formatted listing; `success: Some(true)`.

- **Escalation rejected by policy**  
  Approval policy ≠ OnRequest, payload `{..., "with_escalated_permissions":true, "justification":"needs net"}`  
  Output: RespondToModel `"approval policy is ... reject command — you should not ask for escalated permissions if the approval policy is ..."`; no execution.

- **Inline apply_patch fast path**  
  Payload command array encodes apply_patch grammar.  
  Output: ToolOutput from apply_patch handler (success true) and emits patch events; no shell exec output.

- **Local shell call**  
  Payload: `ToolPayload::LocalShell { params: ShellToolCallParams{command:["echo","local"], workdir:"/repo"} }`  
  Output: same formatting as shell array path; success true.

## Gotchas
- `with_escalated_permissions=true` is rejected unless approval policy is `OnRequest`.
- Inline apply_patch must be intercepted before shell execution to avoid double patches.
- `is_known_safe_command` drives mutating gate; unknown commands serialize tool execution.
- ShellCommandHandler wraps command with user shell; ensure safe quoting to avoid injection differences.
- Timeouts and sandbox denials surface as RespondToModel via ToolEmitter; do not swallow them.

## Sequence Diagram
```
Model -> ToolRouter: ResponseItem(FunctionCall shell|shell_command|local_shell)
ToolRouter -> ShellHandler/ShellCommandHandler: ToolInvocation
Handler -> maybe codex_apply_patch: detect patch
alt patch:
  Handler -> apply_patch flow (events + runtime)
  apply_patch handler -> ToolOutput
else:
  Handler -> ToolEmitter.shell: begin event
  Handler -> ToolOrchestrator.run(ShellRuntime): execute
  ToolOrchestrator -> SandboxManager/Approvals: enforce/possibly retry unsandboxed
  ShellRuntime -> execute_env: run command
  ToolEmitter -> Session: ExecCommandEnd
  ToolEmitter -> Handler: formatted output / error
  Handler -> ToolRouter: ToolOutput or FunctionCallError
end
```
