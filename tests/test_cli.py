import io
import unittest
from contextlib import redirect_stdout

from lincona import __version__, cli


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
