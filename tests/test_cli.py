import io
import pathlib
import sys
from contextlib import redirect_stdout
import unittest

# Ensure src/ is importable without installing the package.
PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC_PATH = PROJECT_ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

from lincona import __version__
from lincona import cli


class TestCli(unittest.TestCase):
    def test_version_constant(self) -> None:
        self.assertEqual(__version__, "0.1.0")

    def test_cli_placeholder_output(self) -> None:
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            exit_code = cli.main([])
        self.assertEqual(exit_code, 0)
        self.assertIn("Lincona CLI placeholder", buffer.getvalue())


if __name__ == "__main__":
    unittest.main()
