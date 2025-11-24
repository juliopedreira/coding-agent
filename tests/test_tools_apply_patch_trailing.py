from lincona.config import FsMode
from lincona.tools.apply_patch import apply_patch
from lincona.tools.fs import FsBoundary


def test_preserve_trailing_newline_when_missing_in_patch(tmp_path):
    target = tmp_path / "file.txt"
    target.write_text("line\n", encoding="utf-8")
    patch = """--- a/file.txt
+++ b/file.txt
@@ -1,1 +1,1 @@
-line
+line"""
    boundary = FsBoundary(FsMode.RESTRICTED, root=tmp_path)
    apply_patch(boundary, patch)
    assert target.read_text(encoding="utf-8").endswith("\n")
