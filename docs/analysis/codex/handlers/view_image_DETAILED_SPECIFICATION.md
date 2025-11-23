# view_image handler — Detailed Specification

Source: `codex-rs/core/src/tools/handlers/view_image.rs`

Purpose
- Allow the model to attach a local image file to the session context; emits an event and injects the image as user input for downstream model calls.

Inputs
- Payload: `ToolPayload::Function { arguments: String }` with JSON `{ "path": "<relative or absolute path>" }`.
- Path is resolved via `TurnContext::resolve_path(Some(path))`, so relative paths are interpreted against the turn cwd.

Outputs
- On success: `ToolOutput::Function { content: "attached local image path", success: Some(true) }`.
- On error: `FunctionCallError::RespondToModel` with message (parse errors, missing file, not a file, cannot attach).

Behaviour
1) Parse JSON args; resolve to absolute path.
2) `fs::metadata` to ensure the path exists and is a file; otherwise RespondToModel.
3) Call `session.inject_input(vec![UserInput::LocalImage { path }])`; if this fails (e.g., no active task) → RespondToModel("unable to attach image (no active task)").
4) Emit `EventMsg::ViewImageToolCall` with `call_id` and resolved path.
5) Return success message.

Pseudocode
```
handle(invocation):
  args = parse ViewImageArgs
  abs_path = turn.resolve_path(args.path)
  metadata = fs::metadata(abs_path)?; if !is_file -> error
  session.inject_input([LocalImage{path: abs_path}]) or error
  session.send_event(ViewImageToolCall{call_id, path})
  return ToolOutput(Function, "attached local image path", success=true)
```

Edge Cases
- Relative paths resolved per turn cwd; ensure consistency when reimplementing.
- Errors are user-facing (no fatal errors in this handler).

Reimplementation Notes
- Keep the exact success content string for compatibility.
- Maintain event emission so clients can react (e.g., UI preview).

## Input/Output Examples
- **Valid image attach**
  Payload: `{"path":"./assets/diagram.png"}` (resolved to `/repo/assets/diagram.png`, file exists)
  Output: ToolOutput content `\"attached local image path\"`, success true; emits ViewImageToolCall event and injects LocalImage input.

- **Path not found**
  Payload: `{"path":"/repo/missing.png"}`
  Output: RespondToModel(\"unable to locate image at `/repo/missing.png`: <io error>\").

- **Path is directory**
  Payload: `{"path":"/repo/assets"}` where assets is dir
  Output: RespondToModel(\"image path `/repo/assets` is not a file\").

- **No active task**
  If `session.inject_input` fails (e.g., no active turn), payload otherwise valid
  Output: RespondToModel("unable to attach image (no active task)").

## Gotchas
- Relative paths resolve via `TurnContext::resolve_path` using turn cwd.
- Only files are allowed; directories or missing paths return errors.
- Success text is static; clients rely on ViewImageToolCall event to show the image.
- Propagate `inject_input` failures; do not silently ignore.

## Sequence Diagram
```
Model -> ToolRouter: ResponseItem(FunctionCall view_image)
ToolRouter -> ViewImageHandler: ToolInvocation
ViewImageHandler -> serde_json: parse args
ViewImageHandler -> fs::metadata: validate file
ViewImageHandler -> Session.inject_input(LocalImage)
ViewImageHandler -> Session.send_event(ViewImageToolCall)
ViewImageHandler -> ToolRouter: ToolOutput or RespondToModel
```
