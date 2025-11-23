# list_dir handler — Detailed Specification

Source: `codex-rs/core/src/tools/handlers/list_dir.rs`

Purpose
- Produce a safe, depth-limited listing of a directory, supporting paging (offset/limit) and BFS traversal, returning formatted lines with indentation and suffix markers.

Inputs
- Payload: `ToolPayload::Function { arguments: String }` with JSON fields:
  - `dir_path` (string, required; must be absolute)
  - `offset` (usize, default 1; 1-indexed start entry; must be >0)
  - `limit` (usize, default 25; max entries to return; must be >0)
  - `depth` (usize, default 2; BFS depth; must be >0)

Outputs
- Success: `ToolOutput::Function { content, success: Some(true) }`, where `content` starts with `"Absolute path: <path>"` followed by formatted entries. If truncated, last line is `"More than <capped_limit> entries found"`.
- Errors: `FunctionCallError::RespondToModel` for parse errors, invalid params, non-absolute path, offset beyond entries, IO failures.

Traversal & Ordering
- BFS using queue of `(dir, relative_prefix, remaining_depth)`.
- For each directory: read entries, collect `(path, relative_path, kind, display data)`, sort by `relative_path` (normalized, slash-separated) before processing; enqueue subdirectories if `remaining_depth > 1`.
- After traversal, full `entries` vector keeps BFS order (parents before children within depth limit).

Paging & Sorting
- After collection, apply `offset`/`limit` to `entries`: slice then sort the selected slice by `name` (relative path) to provide deterministic output page.
- If `offset-1 >= entries.len()` → error "offset exceeds directory entry count".
- If results truncated (end_index < entries.len()) → append "More than <capped_limit> entries found".

Formatting
- Each entry formatted with indentation `depth * INDENTATION_SPACES` (INDENTATION_SPACES=2) based on component count of relative path.
- Suffixes by type: directory `/`, symlink `@`, other `?`, file no suffix.
- Names truncated to `MAX_ENTRY_LENGTH=500` bytes at UTF-8 boundary (both display component and sort key).

Pseudocode
```
handle(invocation):
  args = parse ListDirArgs; validate offset>0, limit>0, depth>0; require abs dir_path
  entries = collect_entries(dir_path, depth) // BFS
  if entries.is_empty(): return ToolOutput("Absolute path: <path>")
  start = offset-1; if start>=len -> error
  end = min(start+limit, len)
  page = entries[start:end]; sort page by name
  lines = [format_entry_line(e) for e in page]
  if end < len: lines.push("More than <limit> entries found")
  content = "Absolute path: <path>\n" + join(lines, "\n")
  return ToolOutput(content, success=true)
```

Edge Cases
- Depth=1 lists only immediate children; deeper levels appear with indentation.
- Large limits handle `usize::MAX` safely by min with remaining_entries.
- Symlink marking only on Unix where applicable (uses FileType methods).

Reimplementation Notes
- Maintain BFS traversal then page-and-sort behavior to match tests.
- Keep absolute-path header line and truncation message wording exact.
- Use UTF-8 safe truncation for names longer than 500 bytes.

## Input/Output Examples
- **Basic list depth 2**
  Payload: `{"dir_path":"/repo","offset":1,"limit":10,"depth":2}`
  Output (example):
  ```
  Absolute path: /repo
  nested/
    child.txt
  root.txt
  ```
  success true.

- **Paging with truncation notice**
  Payload: `{"dir_path":"/repo","offset":1,"limit":3,"depth":3}` when >3 entries exist
  Output ends with `More than 3 entries found`; success true.

- **Offset beyond entries**
  Payload: `{"dir_path":"/repo","offset":999,"limit":5,"depth":1}`
  Output: RespondToModel(\"offset exceeds directory entry count\").

- **Non-absolute path**
  Payload: `{"dir_path":"./relative"}`
  Output: RespondToModel(\"dir_path must be an absolute path\").

- **Depth=0 rejection**
  Payload: `{"dir_path":"/repo","depth":0}`
  Output: RespondToModel("depth must be greater than zero").

## Gotchas
- Paths must be absolute; relative paths are rejected.
- BFS collects all entries before paging; offset beyond count errors even if more pages exist.
- The selected page is re-sorted alphabetically; ordering differs from traversal order.
- Entry names are truncated to 500 bytes at UTF-8 boundaries; deep paths may be clipped.
- Symlink suffix `@` appears only on platforms that expose `FileType::is_symlink` (Unix tests).

## Sequence Diagram
```
Model -> ToolRouter: ResponseItem(FunctionCall list_dir)
ToolRouter -> ListDirHandler: ToolInvocation
ListDirHandler -> serde_json: parse args
ListDirHandler -> collect_entries BFS: fs::read_dir
ListDirHandler -> page + sort slice
ListDirHandler -> ToolRouter: ToolOutput or RespondToModel
```
