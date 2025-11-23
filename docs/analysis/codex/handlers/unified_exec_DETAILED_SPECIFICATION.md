# unified_exec handler — Detailed Specification

Source: `codex-rs/core/src/tools/handlers/unified_exec.rs`
Associated runtime: `codex-rs/core/src/tools/runtimes/unified_exec.rs`

Purpose
- Provide interactive PTY execution to the model via two tools: `exec_command` (start session) and `write_stdin` (send input/poll output). Handles approval/sandboxing and event emission.

Payloads
- `ToolPayload::Function { arguments }` where JSON matches one of the tools:
  - `exec_command`: `{ "cmd": string or array?, "cwd": string, "env"?: object, "with_escalated_permissions"?: bool, "justification"?: string }` (actual schema defined in `spec.rs`).
  - `write_stdin`: `{ "session_id": number, "chars": string, "yield_time_ms"?: number, "max_output_tokens"?: number }`.
- Parsed into tool-specific structs inside handler (see code for exact names).

Outputs
- `exec_command`: On success returns `CustomToolCallOutput` or `FunctionCallOutput` content containing session metadata and initial output (formatted by emitter). Non-zero/denied → RespondToModel with formatted output.
- `write_stdin`: Returns latest output chunk (and potentially session termination info) as model-visible text.
- Errors in arguments → RespondToModel parse error.

Behaviour (high level)
1) Match tool name: `exec_command` or `write_stdin`.
2) Parse JSON args; build request structs:
   - For `exec_command`: build `UnifiedExecRequest` (command Vec<String>, cwd, env map, escalation flags, justification, approval_requirement from execpolicy/sandbox decision).
   - For `write_stdin`: build write request referencing existing session id.
3) For `exec_command`:
   - Emit begin event via `ToolEmitter::unified_exec(command, cwd, source=Agent, interaction_input=None)`.
   - Run `ToolOrchestrator::run` with `UnifiedExecRuntime` (approval + sandbox); runtime opens PTY via `UnifiedExecSessionManager::open_session_with_exec_env`.
   - Finish emitter; map results to Function/Custom outputs with success flag if exit_code==0, else RespondToModel with formatted output.
4) For `write_stdin`:
   - Call `UnifiedExecSessionManager::write_to_session(session_id, chars, yield_time_ms, max_output_tokens)` (inside handler) and return output string; errors → RespondToModel.

Events
- `ExecCommandBegin/End` emitted for `exec_command` with parsed command tokens, cwd, source=Agent, interaction_input optionally used when passing stdin chunks (not used here).

Approval/Sandbox
- Approval requirement is constructed similarly to shell: uses execpolicy + sandbox + escalation flags; orchestrator may retry without sandbox after approval on sandbox denial.
- Escalated permissions (`with_escalated_permissions`) force first attempt with no sandbox.

Pseudocode
```
handle(invocation):
  if tool_name == "write_stdin":
     args = parse WriteStdinArgs; call manager.write(session_id, chars, yield_time_ms, max_output_tokens); return ToolOutput(Function, content)
  else (exec_command):
     args = parse ExecCommandArgs; build UnifiedExecRequest(command_vec, cwd, env, with_escalated_permissions, justification, approval_req)
     emitter.begin(ctx)
     out = Orchestrator.run(UnifiedExecRuntime{manager}, req,...)
     content = emitter.finish(ctx, map out->ExecToolCallOutput)
     return ToolOutput(Function, content, success=exit_code==0)
```

Call Graph
- Handler → (parse args) → if write_stdin → UnifiedExecSessionManager::write_to_session → ToolOutput
- Handler → exec_command → ToolEmitter::unified_exec.begin → ToolOrchestrator::run(UnifiedExecRuntime) → ToolEmitter::finish → ToolOutput

Edge Cases
- Missing/invalid session_id for write_stdin → RespondToModel.
- Sandbox denial/timeout → emitter formats as RespondToModel.
- Empty command list → runtime rejects with `ToolError::Rejected("missing command line for PTY")` → propagated as RespondToModel.

Reimplementation Notes
- Preserve session semantics: exec_command creates new PTY session id; write_stdin continues existing session without closing unless PTY ends.
- Maintain same approval caching key (command, cwd, escalated flag) to avoid repeated prompts.
- Output formatting uses structured formatter from `tools/mod.rs` (structured unless freeform path set elsewhere); replicate truncation rules.

## Input/Output Examples
- **Start PTY session success**
  Payload (`exec_command`): `{"cmd":"python -i","cwd":"/repo"}`
  Output: ToolOutput content with exec formatter showing exit code 0 (or session info); `success: Some(true)` if process exits cleanly.

- **Start PTY denied by sandbox**
  Same payload under restrictive sandbox; runtime returns SandboxErr::Denied → RespondToModel with formatted denial output (exit code -1), no success flag.

- **Start PTY with escalation request**
  Payload includes `"with_escalated_permissions":true,"justification":"needs sudo"`; first attempt unsandboxed; otherwise same outputs as above.

- **write_stdin success**
  Payload (`write_stdin`): `{"session_id":1,"chars":"print(1)\\n","yield_time_ms":200}`
  Output: ToolOutput content = latest PTY output chunk; success Some(true).

- **write_stdin invalid session**
  Payload with unknown session_id → RespondToModel with manager error string (e.g., \"session not found\"), no success flag.

## Gotchas
- Escalation flag (`with_escalated_permissions`) forces the first attempt without sandbox; approvals still apply.
- `write_stdin` must not close sessions; lifecycle is controlled by the PTY/session manager.
- Large interactive output is truncated by the formatter; do not bypass it.
- Approval cache key includes command, cwd, and escalation flag—changing any re-prompts.
- Sandbox denial retry can re-prompt unless policy allows bypass; align with orchestrator rules.

## Sequence Diagram
```
Model -> ToolRouter: ResponseItem(exec_command/write_stdin)
ToolRouter -> UnifiedExecHandler: ToolInvocation
alt exec_command:
  Handler -> ToolEmitter.unified_exec: begin
  Handler -> ToolOrchestrator.run(UnifiedExecRuntime): request PTY
  ToolOrchestrator -> SandboxManager/Approvals: enforce; maybe retry unsandboxed
  UnifiedExecRuntime -> UnifiedExecSessionManager: open_session_with_exec_env
  ToolEmitter -> Session: ExecCommandEnd
  Handler -> ToolRouter: ToolOutput or RespondToModel
else write_stdin:
  Handler -> UnifiedExecSessionManager: write_to_session(session_id, chars,…)
  UnifiedExecSessionManager -> Handler: output or error
  Handler -> ToolRouter: ToolOutput or RespondToModel
end
```
