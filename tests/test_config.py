from pathlib import Path

import pytest
from pydantic import ValidationError

from lincona.config import (
    ApprovalPolicy,
    FsMode,
    LogLevel,
    ModelCapabilities,
    ReasoningEffort,
    Settings,
    Verbosity,
    load_settings,
    write_config,
)


def test_settings_defaults_seeded() -> None:
    settings = Settings()
    assert settings.model == "gpt-5.1-codex-mini"
    assert settings.reasoning_effort == ReasoningEffort.NONE
    assert settings.verbosity == Verbosity.MEDIUM
    assert "gpt-5.1-codex-mini" in settings.models


def test_model_capabilities_validation() -> None:
    with pytest.raises(ValidationError):
        ModelCapabilities(
            reasoning_effort=(ReasoningEffort.LOW,),
            default_reasoning=ReasoningEffort.HIGH,
        )

    with pytest.raises(ValidationError):
        ModelCapabilities(
            verbosity=(Verbosity.LOW,),
            default_verbosity=Verbosity.HIGH,
        )


def test_load_settings_missing_creates_config(tmp_path: Path) -> None:
    cfg = tmp_path / "config.toml"
    settings = load_settings(config_path=cfg, env={}, create_if_missing=True)
    assert cfg.exists()
    assert settings.model == "gpt-5.1-codex-mini"
    assert settings.reasoning_effort == ReasoningEffort.NONE
    assert settings.verbosity == Verbosity.MEDIUM


def test_load_settings_uses_config_defaults(tmp_path: Path) -> None:
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        """
[auth]
api_key = "k"

[model]
id = "gpt-5.1-codex-mini"

[models."gpt-5.1-codex-mini"]
reasoning_effort = ["none","minimal","low","medium","high"]
default_reasoning = "minimal"
verbosity = ["low","medium","high"]
default_verbosity = "high"

[runtime]
fs_mode = "unrestricted"
approval_policy = "always"

[logging]
log_level = "debug"
""",
        encoding="utf-8",
    )

    settings = load_settings(config_path=cfg, env={})
    assert settings.api_key == "k"
    assert settings.reasoning_effort == ReasoningEffort.MINIMAL
    assert settings.verbosity == Verbosity.HIGH
    assert settings.fs_mode is FsMode.UNRESTRICTED
    assert settings.approval_policy is ApprovalPolicy.ALWAYS
    assert settings.log_level is LogLevel.DEBUG


def test_write_and_read_round_trip(tmp_path: Path) -> None:
    cfg = tmp_path / "config.toml"
    models = {
        "gpt-5.1-codex-mini": ModelCapabilities(
            reasoning_effort=(
                ReasoningEffort.NONE,
                ReasoningEffort.MINIMAL,
                ReasoningEffort.LOW,
            ),
            default_reasoning=ReasoningEffort.MINIMAL,
            verbosity=(Verbosity.LOW,),
            default_verbosity=Verbosity.LOW,
        )
    }
    settings = Settings(
        api_key="token",
        model="gpt-5.1-codex-mini",
        reasoning_effort=ReasoningEffort.MINIMAL,
        verbosity=Verbosity.LOW,
        models=models,
        fs_mode=FsMode.UNRESTRICTED,
        approval_policy=ApprovalPolicy.ALWAYS,
        log_level=LogLevel.DEBUG,
    )

    write_config(settings, cfg)
    reloaded = load_settings(config_path=cfg, env={})
    assert reloaded == settings


def test_unknown_model_fails(tmp_path: Path) -> None:
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        """
[model]
id = "gpt-4o"
""",
        encoding="utf-8",
    )
    with pytest.raises(SystemExit):
        load_settings(config_path=cfg, env={})


def test_missing_model_capabilities_gpt5_autoseeded(tmp_path: Path) -> None:
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        """
[model]
id = "gpt-5.new"
""",
        encoding="utf-8",
    )
    settings = load_settings(config_path=cfg, env={})
    assert settings.model == "gpt-5.new"
    assert settings.reasoning_effort in settings.models["gpt-5.new"].reasoning_effort


def test_write_config_skips_empty_sections(tmp_path: Path) -> None:
    cfg = tmp_path / "config.toml"
    settings = Settings()
    write_config(settings, cfg)
    text = cfg.read_text()
    assert "[auth]" not in text  # api_key None => section omitted


def test_verbosity_default_first_item_when_missing_default(tmp_path: Path) -> None:
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        """
[model]
id = "gpt-5.1-codex-mini"

[models."gpt-5.1-codex-mini"]
reasoning_effort = ["none","minimal"]
default_reasoning = "none"
verbosity = ["low","medium"]
""",
        encoding="utf-8",
    )
    settings = load_settings(config_path=cfg, env={})
    assert settings.verbosity == Verbosity.LOW


def test_verbosity_override_rejected_when_not_supported(tmp_path: Path) -> None:
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        """
[model]
id = "gpt-5.1-codex-mini"
verbosity = "high"

[models."gpt-5.1-codex-mini"]
reasoning_effort = ["none"]
default_reasoning = "none"
verbosity = []
""",
        encoding="utf-8",
    )
    with pytest.raises(SystemExit):
        load_settings(config_path=cfg, env={})
