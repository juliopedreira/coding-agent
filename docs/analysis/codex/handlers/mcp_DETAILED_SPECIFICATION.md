# mcp handler — Detailed Specification

Source: `codex-rs/core/src/tools/handlers/mcp.rs`

Purpose
- Bridge MCP tool calls produced by the model to configured MCP servers via the session’s MCP connection manager, returning either MCP or function outputs as appropriate.

Inputs
- Payload: `ToolPayload::Mcp { server: String, tool: String, raw_arguments: String }` supplied by `ToolRouter` when the model uses an MCP-qualified tool name (parsed via `Session::parse_mcp_tool_name`).

Outputs
- If MCP call returns MCP result: `ToolOutput::Mcp { result: Result<CallToolResult, String> }`.
- If handler receives a FunctionCallOutput variant: mapped to `ToolOutput::Function { content, content_items, success }`.
- Errors: `FunctionCallError::RespondToModel` for unsupported payload or unexpected response variant; any internal errors are surfaced by `handle_mcp_tool_call` as model-visible failures.

Behaviour
1) Validate payload is MCP; otherwise RespondToModel.
2) Call `handle_mcp_tool_call(session, turn, call_id, server, tool, arguments_str)`.
3) Map returned `ResponseInputItem`:
   - `McpToolCallOutput { result }` → ToolOutput::Mcp { result }.
   - `FunctionCallOutput { output }` → ToolOutput::Function { content, content_items, success }.
   - Any other variant → RespondToModel("mcp handler received unexpected response variant").

Pseudocode
```
handle(invocation):
  (server, tool, raw_args) = expect_mcp_payload(payload) or error
  resp = handle_mcp_tool_call(session, turn, call_id, server, tool, raw_args)
  match resp:
    McpToolCallOutput{result} -> ToolOutput::Mcp{result}
    FunctionCallOutput{output} -> ToolOutput::Function{content, content_items, success}
    _ -> error RespondToModel
```

Edge Cases
- Any errors inside `handle_mcp_tool_call` are propagated as `ResponseInputItem` already encoded for the model (success flag or MCP error result).

Reimplementation Notes
- Must preserve dual return capability (Function vs MCP output) since MCP tools may return either shape depending on downstream server behavior.
- No sandbox/approval logic here; execution occurs inside MCP server.

## Input/Output Examples
- **Standard MCP tool call success**
  Payload: `ToolPayload::Mcp { server: "figma".into(), tool: "list_files".into(), raw_arguments: "{\"project\":\"123\"}".into() }`
  Downstream returns `McpToolCallOutput { result: Ok(CallToolResult{...}) }` → ToolOutput::Mcp with same result; success determined by `is_error` inside CallToolResult.

- **MCP tool returns function output**
  Downstream responds with `ResponseInputItem::FunctionCallOutput{ output: { content:\"ok\", content_items:None, success:Some(true) }}` → ToolOutput::Function mirrored.

- **Unsupported payload**
  Payload is Function/Custom/etc. → RespondToModel(\"mcp handler received unsupported payload\").

- **Unexpected variant**
  If `handle_mcp_tool_call` returns other ResponseInputItem → RespondToModel(\"mcp handler received unexpected response variant\").

- **Downstream MCP error**
  `result: Err("timeout")` → ToolOutput::Mcp with Err("timeout"); model sees error via MCP result fields.

## Gotchas
- Payload must be MCP; non-MCP payloads are rejected even if tool name matches.
- `handle_mcp_tool_call` may return FunctionCallOutput; pass through without altering content/success.
- Do not infer success from presence of result; use `CallToolResult.is_error`.
- No sandbox/approval applied here—MCP server governs execution.

## Sequence Diagram
```
Model -> ToolRouter: ResponseItem(FunctionCall mcp_tool)
ToolRouter -> McpHandler: ToolInvocation (Mcp payload)
McpHandler -> handle_mcp_tool_call(session, turn, call_id, server, tool, args)
handle_mcp_tool_call -> MCP server: execute tool
MCP server -> handle_mcp_tool_call: ResponseInputItem (McpToolCallOutput | FunctionCallOutput)
McpHandler -> ToolRouter: ToolOutput (Mcp or Function) or RespondToModel
```
