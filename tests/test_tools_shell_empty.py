import pytest

from lincona.config import FsMode
from lincona.tools.fs import FsBoundary
from lincona.tools.shell import run_shell


def test_shell_rejects_empty_command(tmp_path):
    boundary = FsBoundary(FsMode.RESTRICTED, root=tmp_path)
    with pytest.raises(ValueError):
        run_shell(boundary, "   ")
