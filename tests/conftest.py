import pathlib
import shutil
import sys

import pytest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC_PATH = PROJECT_ROOT / "src"

# Ensure src/ is importable when running tests without installing the package.
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))


@pytest.fixture(autouse=True)
def _isolate_lincona_home(monkeypatch):
    """Ensure tests never touch the user's real ~/.lincona.

    We point LINCONA_HOME to a repo-local .work directory and wipe it before
    each test for isolation.
    """

    home = PROJECT_ROOT / ".work"
    if home.exists():
        shutil.rmtree(home)
    home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("LINCONA_HOME", str(home))
    yield
