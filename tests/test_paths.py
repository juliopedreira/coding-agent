from pathlib import Path

from lincona import paths


def test_get_lincona_home_defaults(monkeypatch):
    monkeypatch.delenv("LINCONA_HOME", raising=False)
    home = paths.get_lincona_home()
    assert home.name == ".lincona"


def test_get_lincona_home_env(monkeypatch, tmp_path: Path):
    target = tmp_path / "custom"
    monkeypatch.setenv("LINCONA_HOME", str(target))
    assert paths.get_lincona_home() == target
