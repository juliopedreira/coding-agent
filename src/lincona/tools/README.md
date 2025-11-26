# Tools Reference

This file documents the built-in tools, their inputs/outputs (Pydantic schemas),
and example payloads. All tools are registered via `tool_registrations()` in
their module; `ToolRouter` gathers them automatically.

## list_dir
- **Description**: List directory entries breadth-first up to a depth.
- **Input (ListDirInput)**:
  ```json
  {
    "path": ".",
    "depth": 2,
    "offset": 0,
    "limit": 200
  }
  ```
- **Output (ListDirOutput)**:
  ```json
  {
    "entries": ["src/", "README.md", "pyproject.toml"]
  }
  ```

- **Schema**:
  ```json
  {
    "properties": {
      "path": {"default": ".", "description": "Root directory to list from.", "title": "Path", "type": "string"},
      "depth": {"default": 2, "description": "Maximum depth to traverse (BFS).", "minimum": 0, "title": "Depth", "type": "integer"},
      "offset": {"default": 0, "description": "Number of entries to skip from the start.", "minimum": 0, "title": "Offset", "type": "integer"},
      "limit": {"default": 200, "description": "Maximum number of entries to return.", "minimum": 1, "title": "Limit", "type": "integer"}
    },
    "title": "ListDirInput",
    "type": "object",
    "required": ["path", "depth", "offset", "limit"],
    "additionalProperties": false
  }
  ```

## read_file
- **Description**: Read a slice of a file with optional indentation formatting.
- **Input (ReadFileInput)**:
  ```json
  {
    "path": "src/main.py",
    "offset": 0,
    "limit": 120,
    "mode": "slice",
    "indent": "    "
  }
  ```
- **Output (ReadFileOutput)**:
  ```json
  {
    "text": "def hello():\\n    return 'hi'\\n",
    "truncated": false
  }
  ```

- **Schema**:
  ```json
  {
    "properties": {
      "path": {"description": "File path to read.", "title": "Path", "type": "string"},
      "offset": {"default": 0, "description": "Starting line (0-indexed).", "minimum": 0, "title": "Offset", "type": "integer"},
      "limit": {"default": 400, "description": "Maximum number of lines to return.", "minimum": 1, "title": "Limit", "type": "integer"},
      "mode": {"default": "slice", "description": "Either 'slice' or 'indentation'.", "title": "Mode", "type": "string"},
      "indent": {"default": "    ", "description": "Indentation prefix when mode='indentation'.", "title": "Indent", "type": "string"}
    },
    "required": ["path", "offset", "limit", "mode", "indent"],
    "title": "ReadFileInput",
    "type": "object",
    "additionalProperties": false
  }
  ```

## grep_files
- **Description**: Recursive regex search with optional include globs.
- **Input (GrepFilesInput)**:
  ```json
  {
    "pattern": "TODO",
    "path": "src",
    "include": ["*.py"],
    "limit": 50
  }
  ```
- **Output (GrepFilesOutput)**:
  ```json
  {
    "results": [
      {
        "file": "utils/helpers.py",
        "matches": [
          {"line_num": 14, "line": "# TODO refine error handling"}
        ]
      }
    ]
  }
  ```

- **Schema**:
  ```json
  {
    "properties": {
      "pattern": {"description": "Regex pattern to search for.", "title": "Pattern", "type": "string"},
      "path": {"default": ".", "description": "Root directory to search under.", "title": "Path", "type": "string"},
      "include": {
        "anyOf": [
          {"items": {"type": "string"}, "type": "array"},
          {"type": "null"}
        ],
        "default": null,
        "description": "Optional glob filters to include.",
        "title": "Include"
      },
      "limit": {"default": 200, "description": "Maximum matches to return.", "minimum": 1, "title": "Limit", "type": "integer"}
    },
    "required": ["pattern", "path", "include", "limit"],
    "title": "GrepFilesInput",
    "type": "object",
    "additionalProperties": false
  }
  ```

## apply_patch_json
- **Description**: Apply a unified diff.
- **Input (ApplyPatchInput)**:
  ```json
  {
    "patch": "--- a/file.txt\\n+++ b/file.txt\\n@@ -1,1 +1,1 @@\\n-old\\n+new\\n"
  }
  ```
- **Output (ApplyPatchOutput)**:
  ```json
  {
    "results": [
      {"path": "file.txt", "bytes_written": 4, "created": false}
    ]
  }
  ```

- **Schema**:
  ```json
  {
    "properties": {
      "patch": {"description": "Unified diff text or freeform apply_patch envelope.", "title": "Patch", "type": "string"}
    },
    "required": ["patch"],
    "title": "ApplyPatchInput",
    "type": "object",
    "additionalProperties": false
  }
  ```

## apply_patch_freeform
- **Description**: Apply a patch using the apply_patch freeform envelope (Begin/End Patch).
- **Input**: Same schema as `apply_patch_json` but with freeform wrapper.
- **Output**: Same as `apply_patch_json`.

- **Schema**:
  ```json
  {
    "properties": {
      "patch": {"description": "Unified diff text or freeform apply_patch envelope.", "title": "Patch", "type": "string"}
    },
    "required": ["patch"],
    "title": "ApplyPatchInput",
    "type": "object",
    "additionalProperties": false
  }
  ```

## shell
- **Description**: Run a shell command with truncation and timeout protections.
- **Input (ShellInput)**:
  ```json
  {
    "command": "echo hi",
    "workdir": ".",
    "timeout_ms": 60000
  }
  ```
- **Output (ShellOutput)**:
  ```json
  {
    "stdout": "hi\\n",
    "stderr": "",
    "returncode": 0,
    "stdout_truncated": false,
    "stderr_truncated": false,
    "timeout": false,
    "message": null
  }
  ```

- **Schema**:
  ```json
  {
    "properties": {
      "command": {"description": "Shell command to run.", "title": "Command", "type": "string"},
      "workdir": {
        "anyOf": [{"type": "string"}, {"type": "null"}],
        "default": null,
        "description": "Working directory (optional).",
        "title": "Workdir"
      },
      "timeout_ms": {"default": 60000, "description": "Timeout in milliseconds.", "minimum": 1, "title": "Timeout Ms", "type": "integer"}
    },
    "required": ["command", "workdir", "timeout_ms"],
    "title": "ShellInput",
    "type": "object",
    "additionalProperties": false
  }
  ```

## exec_command
- **Description**: Start a PTY-backed long-running command.
- **Input (ExecCommandInput)**:
  ```json
  {
    "session_id": "sess-1",
    "cmd": "bash",
    "workdir": "."
  }
  ```
- **Output (ExecCommandOutput)**:
  ```json
  {
    "output": "",
    "truncated": false
  }
  ```

- **Schema**:
  ```json
  {
    "properties": {
      "session_id": {"description": "Opaque PTY session identifier.", "title": "Session Id", "type": "string"},
      "cmd": {"description": "Command to execute in PTY.", "title": "Cmd", "type": "string"},
      "workdir": {
        "anyOf": [{"type": "string"}, {"type": "null"}],
        "default": null,
        "description": "Working directory (optional).",
        "title": "Workdir"
      }
    },
    "required": ["session_id", "cmd", "workdir"],
    "title": "ExecCommandInput",
    "type": "object",
    "additionalProperties": false
  }
  ```

## write_stdin
- **Description**: Send input to an existing PTY session created by `exec_command`.
- **Input (WriteStdinInput)**:
  ```json
  {
    "session_id": "sess-1",
    "chars": "echo hi\\n"
  }
  ```
- **Output (WriteStdinOutput)**:
  ```json
  {
    "output": "echo hi\\nhi\\n",
    "truncated": false
  }
  ```

- **Schema**:
  ```json
  {
    "properties": {
      "session_id": {"description": "Existing PTY session id.", "title": "Session Id", "type": "string"},
      "chars": {"description": "Characters to write to stdin.", "title": "Chars", "type": "string"}
    },
    "required": ["session_id", "chars"],
    "title": "WriteStdinInput",
    "type": "object",
    "additionalProperties": false
  }
  ```

## Shared behavior
- Boundary enforcement: All tools run under `FsBoundary`.
- Approval: Mutating/command tools (`apply_patch_*`, `shell`, `exec_command`, `write_stdin`) require approval policy to allow execution.
- Logging: Requests at INFO, responses at DEBUG in the session log.
