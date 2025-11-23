# read_file handler — Detailed Specification

Source: `codex-rs/core/src/tools/handlers/read_file.rs`

Purpose
- Safely read and return portions of a file for the model, supporting simple slices or indentation-aware block extraction while avoiding runaway output.

Inputs
- Payload: `ToolPayload::Function { arguments: String }` where JSON schema:
  - `file_path` (string, must be absolute)
  - `offset` (usize, default 1; 1-indexed starting line)
  - `limit` (usize, default 2000; max lines to return)
  - `mode` ("slice" | "indentation"; default slice)
  - `indentation` (object, only for indentation mode):
    - `anchor_line` (usize, optional; defaults to offset)
    - `max_levels` (usize, default 0 meaning unlimited)
    - `include_siblings` (bool, default true)
    - `include_header` (bool, default true)
    - `max_lines` (usize, optional hard cap)

Output
- On success: `ToolOutput::Function { content, content_items: None, success: Some(true) }` where `content` is newline-joined lines with prefixes showing line numbers, indentation and truncated long lines.
- On error: `FunctionCallError::RespondToModel` with user-visible text.

Behaviour
1) Parse JSON args; reject non-absolute `file_path`, offset==0, limit==0.
2) Depending on `mode`:
   - Slice: sequentially read file lines via async BufReader; collect lines starting at `offset` up to `limit` lines; format each with line number and tab expansion.
   - Indentation: use indentation args to find a block rooted at anchor_line; walk up/down to include siblings/header respecting max_levels/max_lines; uses helpers to classify blank/comment lines; collects until limits hit.
3) Lines longer than `MAX_LINE_LENGTH` (500) are truncated using `take_bytes_at_char_boundary`; tab width fixed at 4 for display alignment.
4) Return collected lines joined with `\n`.

Pseudocode (slice mode)
```
read_slice(path, offset, limit):
  open file async
  for each line with 1-based index:
     if idx < offset: continue
     if collected == limit: break
     format_line(idx, line)
  return collected
```

Pseudocode (indentation mode)
```
read_block(path, offset, limit, opts):
  read all lines into LineRecord (number, raw, display, indent, blank/comment flags)
  anchor = opts.anchor_line.unwrap_or(offset)
  determine anchor indent; collect lines downward while indent >= anchor_indent and within max_levels; include siblings/header if flags set; cap by limit/max_lines; format_line for each
  return collected
```

Edge Cases
- Missing file or IO error → RespondToModel("failed to read file: ...").
- Non-absolute path → RespondToModel.
- Offset beyond EOF returns empty content (no error).

Dependencies/Constants
- `MAX_LINE_LENGTH=500`, `TAB_WIDTH=4`, `COMMENT_PREFIXES=["#","//","--"]`.
- Uses `take_bytes_at_char_boundary` to avoid breaking UTF-8 when truncating.

Reimplementation Notes
- Preserve line-number formatting and trimming logic from `format_line` (see source) for compatibility.
- Maintain indentation heuristics (blank/comment detection) to match block mode output.
- All errors should be user-facing via RespondToModel; do not throw fatal errors from this handler.

## Input/Output Examples
- **Slice basic**  
  Payload: `{"file_path":"/repo/src/lib.rs","offset":10,"limit":5,"mode":"slice"}`  
  Output: 5 numbered lines starting at 10; success true.

- **Slice offset past EOF**  
  Payload: `{"file_path":"/repo/src/empty.rs","offset":999,"limit":10}`  
  Output: empty content string; success true.

- **Indentation block with header/siblings**  
  Payload: `{"file_path":"/repo/app.py","offset":42,"limit":50,"mode":"indentation","indentation":{"anchor_line":42,"max_levels":1,"include_siblings":true,"include_header":true}}`  
  Output: formatted block covering the anchor’s indentation level and siblings; success true.

- **Invalid path (relative)**  
  Payload: `{"file_path":"relative.txt"}`  
  Output: RespondToModel(\"file_path must be an absolute path\").

- **Zero limit**  
  Payload: `{"file_path":"/repo/a.txt","limit":0}`  
  Output: RespondToModel("limit must be greater than zero").

## Gotchas
- Paths must be absolute; relative paths are rejected even if they would resolve.
- Very long lines are truncated at UTF-8 boundaries; trailing newlines may be absent.
- Indentation mode reads the whole file into memory; large files may be slow.
- Comment detection is heuristic (`#`, `//`, `--`); other comment styles are treated as code.

## Sequence Diagram
```
Model -> ToolRouter: ResponseItem(FunctionCall read_file)
ToolRouter -> ReadFileHandler: ToolInvocation
ReadFileHandler -> serde_json: parse args
ReadFileHandler -> file IO: slice or indentation collection
ReadFileHandler -> ToolRouter: ToolOutput or RespondToModel
```
