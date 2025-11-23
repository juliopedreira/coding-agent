# mcp_resource handler — Detailed Specification

Source: `codex-rs/core/src/tools/handlers/mcp_resource.rs`

Purpose
- Provide three MCP resource utilities to the model: list resources, list resource templates, and read a resource. Emits begin/end events with timing and returns JSON-formatted payloads.

Supported Tools (tool_name)
- `list_mcp_resources`
- `list_mcp_resource_templates`
- `read_mcp_resource`

Inputs
- Payload: `ToolPayload::Function { arguments: String }`; arguments may be empty (treated as None) or JSON objects:
  - list_mcp_resources: `{ "server"?: string, "cursor"?: string }`
  - list_mcp_resource_templates: `{ "server"?: string, "cursor"?: string }`
  - read_mcp_resource: `{ "server": string, "uri": string }` (required)

Outputs
- All successful calls return `ToolOutput::Function` with `content` = serialized JSON string of payload, `success: Some(true)`.
- Errors (missing fields, cursor misuse, MCP failures, serialization issues) return `FunctionCallError::RespondToModel`.

Events
- Emits `EventMsg::McpToolCallBegin` before contacting MCP; `EventMsg::McpToolCallEnd` after, including duration and result (CallToolResult or error string). Invocation metadata includes server/tool/arguments.

Behaviour per tool
1) **list_mcp_resources**
   - If `server` provided: optionally pass cursor to `Session::list_resources(server, params)`; payload = `ListResourcesPayload::from_single_server` (includes nextCursor).
   - If `server` omitted: cursor must be None else error; aggregate all servers via `mcp_connection_manager.list_all_resources()`; payload = `ListResourcesPayload::from_all_servers` (sorted by server name).
   - Serialize payload to JSON string and wrap in ToolOutput; emit end event with CallToolResult built from content (is_error = !success).

2) **list_mcp_resource_templates**
   - Same pattern as resources but using `list_resource_templates` and `ListResourceTemplatesPayload` helpers; aggregates/sorts templates.

3) **read_mcp_resource**
   - Require non-empty `server` and `uri`; call `Session::read_resource(server, ReadResourceRequestParams { uri })`.
   - Build `ReadResourcePayload { server, uri, result }`; serialize to JSON string; emit end event.

Common Helpers
- `parse_arguments` parses raw JSON or returns None on empty/whitespace.
- `parse_args` / `parse_args_with_default` deserialize with validation; required string fields normalized (trim, non-empty) via `normalize_required_string`; optional via `normalize_optional_string` (empties to None).
- `call_tool_result_from_content` converts the function content string and success flag into `CallToolResult` (text block, is_error flips success).

Pseudocode (list example)
```
handle(invocation):
  args_value = parse_arguments(raw_args)
  match tool_name:
    list_mcp_resources -> payload = build_resources_payload(args_value)
    list_mcp_resource_templates -> payload = build_templates_payload(args_value)
    read_mcp_resource -> payload = build_read_payload(args_value)
  emit_begin(call_id, invocation)
  start_timer
  payload_result = perform_mcp_calls(...)
  serialize payload -> ToolOutput::Function
  emit_end(duration, CallToolResult from content, success/error)
  return ToolOutput or error
```

Edge Cases
- Cursor provided without server → RespondToModel("cursor can only be used when a server is specified").
- Empty or whitespace arguments treated as None.
- Serialization failure surfaces as RespondToModel.

Reimplementation Notes
- Preserve sorting for aggregated outputs (server name asc; resources/templates kept in order). Exact JSON field names: server, resources/resourceTemplates, nextCursor.
- Maintain begin/end event emission with duration and error strings; success flag influences `is_error`.

## Input/Output Examples
- **List resources for specific server**
  Payload: `{"server":"figma","cursor":null}`
  Output: JSON string `{"server":"figma","resources":[...],"nextCursor":null}` wrapped in ToolOutput success true; begin/end events emitted.

- **List resources all servers**
  Payload: `{}` (empty or whitespace)
  Output: JSON string with `server:null` and merged `resources` sorted by server name; success true.

- **List resources with cursor but no server**
  Payload: `{"cursor":"abc"}`
  Output: RespondToModel(\"cursor can only be used when a server is specified\").

- **Read resource success**
  Payload: `{"server":"figma","uri":"memo://123"}`
  Output: JSON string containing server, uri, and read result; success true.

- **Read resource missing required field**
  Payload: `{"uri":"memo://123"}`
  Output: RespondToModel(\"server must be provided\").

- **MCP backend error**
  If Session::read_resource returns error, output RespondToModel("resources/read failed: <err>"); end event includes error string.

## Gotchas
- Empty arguments are treated as None; list calls with a cursor but no server produce an error.
- Aggregated outputs are sorted by server name; changing order can break clients/tests.
- Responses are JSON strings; callers must parse—no structured items are returned.
- Begin/End events must include duration and result; CallToolResult is derived from content and success flag.

## Sequence Diagram
```
Model -> ToolRouter: ResponseItem(FunctionCall list/read mcp resource)
ToolRouter -> McpResourceHandler: ToolInvocation
McpResourceHandler -> parse_arguments/parse_args*: decode JSON or defaults
McpResourceHandler -> emit_tool_call_begin(Event)
McpResourceHandler -> Session: list/read resources/templates
Session -> McpResourceHandler: result or error
McpResourceHandler -> serialize_function_output -> ToolOutput::Function
McpResourceHandler -> emit_tool_call_end(Event, CallToolResult)
McpResourceHandler -> ToolRouter: ToolOutput or RespondToModel
```
