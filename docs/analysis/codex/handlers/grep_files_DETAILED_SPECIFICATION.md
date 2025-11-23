# grep_files handler — Detailed Specification

Source: `codex-rs/core/src/tools/handlers/grep_files.rs`

Purpose
- Perform a fast ripgrep search for files containing a pattern, returning matching file paths (not matched lines) up to a limit.

Inputs
- Payload: `ToolPayload::Function { arguments: String }` with JSON fields:
  - `pattern` (string, required; trimmed; must be non-empty)
  - `include` (optional glob string; empty string treated as None)
  - `path` (optional string; resolved via `TurnContext::resolve_path`; may be relative to turn cwd; must exist)
  - `limit` (usize, default 100; must be >0; capped at 2000)

Outputs
- Success with matches: `ToolOutput::Function { content: joined_lines, success: Some(true) }`, where `joined_lines` is newline-separated file paths (order from ripgrep sorting).
- No matches: same output with content `"No matches found."` and `success: Some(false)`.
- Errors: `FunctionCallError::RespondToModel` with descriptive text (parse errors, missing rg, timeout, etc.).

Behaviour
1) Parse JSON args; validate `pattern` non-empty and `limit>0`; cap limit to `MAX_LIMIT=2000`.
2) Resolve `search_path` = `turn.resolve_path(args.path)` (defaults to turn cwd). Verify path exists (`tokio::fs::metadata`).
3) Normalize `include` (trim; drop empty).
4) Build `rg` command:
   - `rg --files-with-matches --sortr=modified --regexp <pattern> --no-messages [--glob <include>] -- <search_path>`
   - Working directory set to `turn.cwd`.
5) Run with `COMMAND_TIMEOUT = 30s` using `tokio::time::timeout`.
6) Interpret exit code:
   - 0 → parse stdout lines into UTF-8 strings; return first `limit` entries.
   - 1 → no matches → empty list.
   - Else → RespondToModel("rg failed: <stderr>").
7) If result list empty → content "No matches found.", success=false; else join with `\n`, success=true.

Pseudocode
```
handle(invocation):
  args = parse GrepFilesArgs
  validate pattern, limit
  limit = min(args.limit, 2000)
  search_path = turn.resolve_path(args.path)
  verify_path_exists(search_path)
  include = normalized args.include
  output = run_rg_search(pattern, include, search_path, limit, turn.cwd)
  if output.is_empty(): return ToolOutput(content="No matches found.", success=false)
  else return ToolOutput(content=join(output, "\n"), success=true)

run_rg_search(...):
  cmd = ["rg", "--files-with-matches", "--sortr=modified", "--regexp", pattern, "--no-messages", maybe "--glob", glob, "--", search_path]
  exec with timeout 30s
  if status 0 -> parse_results(stdout, limit)
  elif status 1 -> []
  else -> error RespondToModel(stderr)
```

Edge Cases
- `rg` not installed or cannot spawn → RespondToModel with install hint.
- Timeout → RespondToModel("rg timed out after 30 seconds").
- Non-existent path → RespondToModel("unable to access `<path>`: ...").
- Non-UTF-8 lines are skipped silently (parse_results only pushes valid UTF-8 lines).

Dependencies
- External binary `rg` must be on PATH.
- Uses tokio async process + timeout; no sandbox logic inside handler (handled upstream in shell tools when executed).

## Input/Output Examples
- **Match with default limit**  
  Payload: `{"pattern":"TODO","path":"/repo"}`  
  Output: newline-separated file paths containing TODO, up to 100 entries; success true.

- **No matches**  
  Payload: `{"pattern":"ZZZ_NOT_FOUND","path":"/repo"}`  
  Output: `content="No matches found."`, `success: Some(false)`.

- **Glob filtered**  
  Payload: `{"pattern":"alpha","path":"/repo","include":"*.rs","limit":5}`  
  Output: Only `.rs` files listed, max 5; success true.

- **Limit capped**  
  Payload: `{"pattern":"foo","limit":5000}`  
  Output: at most 2000 paths (cap applied); success true.

- **Path missing**  
  Payload: `{"pattern":"foo","path":"/missing"}`  
  Output: RespondToModel(\"unable to access `/missing`: <error>\").

- **Empty pattern**  
  Payload: `{"pattern":"   "}`  
  Output: RespondToModel(\"pattern must not be empty\").

- **rg timeout**  
  Large search causing >30s execution → RespondToModel("rg timed out after 30 seconds").

## Gotchas
- Depends on external `rg`; missing binary or PATH issues surface as user-facing error.
- Returns file paths only (`--files-with-matches`), not matched lines—callers must read files for context.
- Limit is applied after parsing; ripgrep still scans full tree until timeout.
- Uses `turn.cwd` as working dir; `path` is resolved before invocation.
- Timeout is fixed at 30s; no partial output is returned on timeout.

## Sequence Diagram
```
Model -> ToolRouter: ResponseItem(FunctionCall grep_files)
ToolRouter -> GrepFilesHandler: ToolInvocation
GrepFilesHandler -> serde_json: parse args
GrepFilesHandler -> verify_path_exists
GrepFilesHandler -> run_rg_search (timeout 30s)
run_rg_search -> rg subprocess: --files-with-matches …
GrepFilesHandler -> ToolRouter: ToolOutput ("No matches" or paths) or RespondToModel
```
