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
    "results": ["utils/helpers.py:14:# TODO refine error handling"]
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

## apply_patch_freeform
- **Description**: Apply a patch using the apply_patch freeform envelope (Begin/End Patch).
- **Input**: Same schema as `apply_patch_json` but with freeform wrapper.
- **Output**: Same as `apply_patch_json`.

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

## Shared behavior
- Boundary enforcement: All tools run under `FsBoundary`.
- Approval: Mutating/command tools (`apply_patch_*`, `shell`, `exec_command`, `write_stdin`) require approval policy to allow execution.
- Logging: Requests at INFO, responses at DEBUG in the session log.
