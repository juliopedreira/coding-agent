import pathlib
import sys


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC_PATH = PROJECT_ROOT / "src"

# Ensure src/ is importable when running tests without installing the package.
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))
