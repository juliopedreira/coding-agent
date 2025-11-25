import pytest

from lincona.config import FsMode
from lincona.tools.apply_patch import ApplyPatchInput
from lincona.tools.exec_pty import ExecCommandInput, PtyManager, WriteStdinInput
from lincona.tools.fs import FsBoundary
from lincona.tools.grep_files import GrepFilesInput
from lincona.tools.list_dir import ListDirInput
from lincona.tools.read_file import ReadFileInput
from lincona.tools.router import _schema_for_model, tool_specs
from lincona.tools.shell import ShellInput

MODELS = [
    ListDirInput,
    ReadFileInput,
    GrepFilesInput,
    ApplyPatchInput,
    ShellInput,
    ExecCommandInput,
    WriteStdinInput,
]


@pytest.mark.parametrize("model", MODELS)
def test_schema_required_matches_properties(model):
    schema = _schema_for_model(model)
    props = schema.get("properties", {}) or {}
    assert set(schema.get("required", [])) == set(props.keys())


@pytest.mark.parametrize("model", MODELS)
def test_schema_no_path_format(model):
    schema = _schema_for_model(model)
    props = schema.get("properties", {}) or {}
    for definition in props.values():
        fmt = definition.get("format")
        assert fmt not in {"path", "Path"}


def test_tool_specs_all_functions():
    boundary = FsBoundary(FsMode.RESTRICTED)
    specs = tool_specs(boundary, PtyManager(boundary))
    names = {spec["function"]["name"] for spec in specs if "function" in spec}
    expected = {
        "list_dir",
        "read_file",
        "grep_files",
        "apply_patch_json",
        "apply_patch_freeform",
        "shell",
        "exec_command",
        "write_stdin",
    }
    assert expected.issubset(names)
