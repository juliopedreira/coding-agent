# update_plan (plan) handler — Detailed Specification

Source: `codex-rs/core/src/tools/handlers/plan.rs`
Tool spec constant: `PLAN_TOOL` (also in this file) used when advertising tool list.

Purpose
- Provide a structured way for the model to record its plan (steps with statuses). Primarily for client consumption; handler stores no state besides emitting an event.

Inputs
- Payload: `ToolPayload::Function { arguments: String }` containing JSON matching `codex_protocol::plan_tool::UpdatePlanArgs`:
  - `explanation` (optional string)
  - `plan`: array of items `{ "step": string, "status": "pending"|"in_progress"|"completed" }` (at most one in_progress expected by description).

Outputs
- On success: `ToolOutput::Function { content: "Plan updated", success: Some(true) }`.
- On error: `FunctionCallError::RespondToModel` (parse failure).

Behaviour
1) Parse arguments into `UpdatePlanArgs` (serde_json). If parsing fails → RespondToModel("failed to parse function arguments: ...").
2) Emit `EventMsg::PlanUpdate(args)` via `session.send_event(turn, ...)`.
3) Return "Plan updated".

Tool Spec (PLAN_TOOL)
- Name: `update_plan`
- Parameters: JSON schema with required `plan` array; `explanation` optional; plan items require `step` and `status` fields, no additional properties.
- Description includes reminder that only one step can be in_progress.

Pseudocode
```
handle(invocation):
  args = parse UpdatePlanArgs(arguments)
  session.send_event(turn, PlanUpdate(args))
  return ToolOutput(Function, "Plan updated", success=true)
```

Edge Cases
- No additional validation of statuses count; relies on model to follow spec.

Reimplementation Notes
- Emit the PlanUpdate event; otherwise behavior is trivial.
- Keep success string stable for clients/tests.

## Input/Output Examples
- **Valid plan update**
  Payload: `{"explanation":"Roadmap","plan":[{"step":"Set up project","status":"completed"},{"step":"Implement feature","status":"in_progress"}]}`
  Output: ToolOutput content `\"Plan updated\"`, success true; PlanUpdate event emitted.

- **Missing required field**
  Payload: `{"explanation":"Oops"}` (no plan array)
  Output: RespondToModel(\"failed to parse function arguments: ...\"), no event.

- **Invalid status value**
  Payload includes `status:"done"` → JSON parse may succeed but model should adhere; if serde rejects, RespondToModel parse error.

## Gotchas
- Handler does not validate uniqueness of in_progress steps; relies on model to follow spec.
- No persistence beyond emitted event; clients must store plan state.
- Any serde parse failure returns model-visible error; keep schema in sync.
- Success message is fixed ("Plan updated"); clients should watch PlanUpdate event instead of parsing text.

## Sequence Diagram
```
Model -> ToolRouter: ResponseItem(FunctionCall update_plan)
ToolRouter -> PlanHandler: ToolInvocation
PlanHandler -> serde_json: parse UpdatePlanArgs
PlanHandler -> Session.send_event(PlanUpdate)
PlanHandler -> ToolRouter: ToolOutput("Plan updated") or RespondToModel
```
