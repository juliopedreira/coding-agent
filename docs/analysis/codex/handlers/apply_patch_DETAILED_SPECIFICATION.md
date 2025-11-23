# apply_patch handler — Detailed Specification

Source: `codex-rs/core/src/tools/handlers/apply_patch.rs`
Related grammar: `codex-rs/core/src/tools/handlers/tool_apply_patch.lark`

Purpose
- Accept an apply_patch tool call (JSON function args or freeform custom input), validate/verify patch text, emit patch events, and execute the patch either inline or via the apply-patch runtime under sandbox/approval control.

Inputs
- Tool payloads accepted:
  - `ToolPayload::Function { arguments: String }` where `arguments` is JSON for `ApplyPatchToolArgs` (`{ "input": "...patch..." }`).
  - `ToolPayload::Custom { input: String }` containing raw apply_patch grammar text.
- Context: `ToolInvocation` carries `Session`, `TurnContext`, shared `TurnDiffTracker`, `call_id`, and `tool_name`.

Outputs
- On success: `ToolOutput::Function { content, content_items: None, success: Some(true) }` where `content` is model-facing text from patch application.
- On failure: `FunctionCallError::RespondToModel` with user-visible string, or `FunctionCallError::Fatal` for unrecoverable issues.

Behaviour (step-by-step)
1) Decode payload: if Function → parse JSON into `ApplyPatchToolArgs` and take `input`; if Custom → use `input`; else error.
2) Verify patch using `codex_apply_patch::maybe_parse_apply_patch_verified(command=["apply_patch", input], cwd=turn.cwd)`.
   - Returns one of: `Body(changes)`, `CorrectnessError`, `ShellParseError`, `NotApplyPatch`.
3) If `CorrectnessError` → RespondToModel("apply_patch verification failed: {err}"). If `ShellParseError` → trace log + RespondToModel("apply_patch handler received invalid patch input"). If `NotApplyPatch` → RespondToModel("apply_patch handler received non-apply_patch input").
4) If `Body(changes)` → call `apply_patch::apply_patch(session, turn, call_id, changes)` which yields `InternalApplyPatchInvocation`:
   - `Output(item)` → return its `content` in `ToolOutput::Function`.
   - `DelegateToExec(apply)` →
     a) Emit begin event via `ToolEmitter::apply_patch(convert_apply_patch_to_protocol(&apply.action), !apply.user_explicitly_approved_this_action)` with tracker for diffing.
     b) Build `ApplyPatchRequest` with patch text, cwd, timeout_ms=None, user_explicitly_approved flag, and `codex_exe` from turn (Linux sandbox wrapper path).
     c) Run `ApplyPatchRuntime` through `ToolOrchestrator::run`, honoring sandbox + approval policy.
     d) Finish event via emitter; return resulting content in `ToolOutput::Function`.
5) All successes set `success: Some(true)`; errors map to model-visible text.

Approval/Sandbox
- Approval for delegations handled in runtime/orchestrator; upstream apply_patch verification already considered user explicit approval flag.
- No direct sandbox logic in handler; relies on runtime and orchestrator.

Pseudocode
```
handle(invocation):
  payload = invocation.payload
  input = match payload:
    Function -> parse JSON ApplyPatchToolArgs; input
    Custom -> input
    _ -> error RespondToModel

  result = verify_apply_patch(command=["apply_patch", input], cwd=turn.cwd)
  match result:
    CorrectnessError(e) -> error RespondToModel("apply_patch verification failed: {e}")
    ShellParseError(_) -> error RespondToModel("apply_patch handler received invalid patch input")
    NotApplyPatch -> error RespondToModel("apply_patch handler received non-apply_patch input")
    Body(changes):
      invocation_result = apply_patch(session, turn, call_id, changes)
      if Output(item): return ToolOutput(Function, content=item?)
      if DelegateToExec(apply):
        emitter = ToolEmitter::apply_patch(convert_apply_patch_to_protocol(apply.action), !apply.user_explicitly_approved)
        emitter.begin(ctx)
        req = ApplyPatchRequest{patch=apply.action.patch, cwd=apply.action.cwd, timeout_ms=None, user_explicitly_approved=apply.user_explicitly_approved, codex_exe=turn.codex_linux_sandbox_exe}
        out = Orchestrator.run(ApplyPatchRuntime, req, tool_ctx, turn, approval_policy)
        content = emitter.finish(ctx, out)?
        return ToolOutput(Function, content, success=true)
```

Call Graph (simplified)
- apply_patch::handle → verify via codex_apply_patch → apply_patch::apply_patch → (Output | DelegateToExec)
- DelegateToExec path: ToolEmitter::apply_patch.begin → ToolOrchestrator::run(ApplyPatchRuntime) → ToolEmitter::finish → ToolOutput

Edge Cases
- Non-absolute or malformed patch text: verification errors as RespondToModel.
- User already approved apply_patch: runtime skips re-approval by returning ApprovedForSession.
- Sandbox denial/timeouts handled in runtime/emitter (mapped to model-visible errors).

Reimplementation Notes
- Must reproduce grammar in `tool_apply_patch.lark` for freeform mode.
- Preserve event emissions (PatchApplyBegin/PatchApplyEnd/TurnDiff) and success flag semantics.
- Ensure truncation/formatting handled by emitter/runtime (not handler) for consistency.

## Input/Output Examples
- **Freeform patch, verified, inline apply succeeds**
  Input payload (Function): `{"input":"*** Begin Patch\n*** Update File: foo.txt\n@@\n-foo\n+bar\n*** End Patch\n"}`
  Output: `ToolOutput::Function` with `content` = apply_patch success text (from `apply_patch::apply_patch`), `success: Some(true)`.

- **Freeform patch, verification fails**
  Input payload: malformed grammar (e.g., missing header).
  Output: `FunctionCallError::RespondToModel("apply_patch verification failed: <reason>")`.

- **Custom payload delegated to exec**
  Input payload (Custom): same patch text; `codex_apply_patch` returns `DelegateToExec`.
  Output: `ToolOutput::Function` with content from `ApplyPatchRuntime` (formatted exec output); success true if exit code 0, otherwise RespondToModel with stderr.

- **Shell parse error**
  Input payload containing tricky shell quoting that fails verification.
  Output: `FunctionCallError::RespondToModel("apply_patch handler received invalid patch input")`.

- **Non-apply_patch text**
  Input payload: `{"input":"echo hi"}`
  Output: `FunctionCallError::RespondToModel("apply_patch handler received non-apply_patch input")`.

## Gotchas
- Verification can return `DelegateToExec`; caller must still emit patch events before executing.
- User-approved flag skips extra approval; but sandbox may still deny and be retried unsandboxed.
- Patch text must be UTF-8; invalid bytes will fail verification.
- Inline apply_patch in shell handler shares this logic; keep behavior identical to avoid divergence.

## Sequence Diagram
```
Model -> ToolRouter: ResponseItem(FunctionCall apply_patch)
ToolRouter -> apply_patch handler: ToolInvocation
apply_patch handler -> codex_apply_patch: verify patch
codex_apply_patch -> apply_patch handler: Body(changes)|Delegate|Error
apply_patch handler -> apply_patch::apply_patch: if Body(changes)
apply_patch::apply_patch -> apply_patch handler: Output|DelegateToExec
apply_patch handler -> ToolEmitter.apply_patch: begin (if Delegate)
apply_patch handler -> ToolOrchestrator.run(ApplyPatchRuntime): execute patch
ToolOrchestrator -> SandboxManager/Approvals: enforce
ApplyPatchRuntime -> ToolEmitter.apply_patch: finish with ExecToolCallOutput
ToolEmitter -> Session: PatchApplyEnd + TurnDiff events
apply_patch handler -> ToolRouter: ToolOutput / FunctionCallError
```
