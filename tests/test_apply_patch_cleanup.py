from pathlib import Path

import pytest

from lincona.config import FsMode
from lincona.tools import apply_patch as apply_patch_mod
from lincona.tools.apply_patch import ApplyPatchInput, ApplyPatchTool
from lincona.tools.fs import FsBoundary


def test_apply_patch_cleans_temp_on_replace_failure(monkeypatch, tmp_path):
    boundary = FsBoundary(FsMode.RESTRICTED, root=tmp_path)
    tool = ApplyPatchTool(boundary)

    patch = """--- a/x.txt\n+++ b/x.txt\n@@ -0,0 +1,1 @@\n+hi\n"""

    class FailingPath(Path):
        _flavour = Path()._flavour

        def replace(self, target):  # type: ignore[override]
            raise OSError("simulated replace failure")

    # Force apply_patch to use FailingPath so replace() throws
    monkeypatch.setattr(apply_patch_mod, "Path", FailingPath)

    with pytest.raises(OSError):
        tool.execute(ApplyPatchInput(patch=patch))

    # Ensure no temp files left behind
    leftovers = list(tmp_path.rglob("*"))
    assert leftovers == []
