import tomllib
from collections.abc import Mapping
from pathlib import Path

import pytest
from pydantic import ValidationError

from lincona.config import ApprovalPolicy, FsMode, LogLevel, ReasoningEffort, Settings, load_settings, write_config


def test_settings_defaults() -> None:
    settings = Settings()

    assert settings.api_key is None
    assert settings.model == "gpt-4.1-mini"
    assert settings.reasoning_effort is ReasoningEffort.MEDIUM
    assert settings.fs_mode is FsMode.RESTRICTED
    assert settings.approval_policy is ApprovalPolicy.ON_REQUEST
    assert settings.log_level is LogLevel.INFO


@pytest.mark.parametrize(
    "field_name, invalid_value",
    [
        ("fs_mode", "invalid"),
        ("approval_policy", "maybe"),
        ("log_level", "verbose"),
        ("reasoning_effort", "extreme"),
    ],
)
def test_invalid_enum_values_raise(field_name: str, invalid_value: str) -> None:
    with pytest.raises(ValidationError):
        Settings(**{field_name: invalid_value})


def test_string_values_coerce_to_enums() -> None:
    settings = Settings(
        fs_mode="unrestricted",
        approval_policy="always",
        log_level="debug",
        reasoning_effort="high",
    )

    assert settings.fs_mode is FsMode.UNRESTRICTED
    assert settings.approval_policy is ApprovalPolicy.ALWAYS
    assert settings.log_level is LogLevel.DEBUG
    assert settings.reasoning_effort is ReasoningEffort.HIGH


def test_model_cannot_be_empty() -> None:
    with pytest.raises(ValidationError):
        Settings(model="   ")


def test_api_key_strips_whitespace() -> None:
    settings = Settings(api_key="  secret  ")

    assert settings.api_key == "secret"


def test_load_settings_defaults_without_config(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"

    settings = load_settings(config_path=config_path, env={})

    assert settings.model == "gpt-4.1-mini"
    assert config_path.exists() is False


def test_load_settings_reads_config(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        """
[auth]
api_key = "from_config"

[model]
id = "gpt-4.1"
reasoning_effort = "low"

[runtime]
fs_mode = "unrestricted"
approval_policy = "always"

[logging]
log_level = "debug"
"""
    )

    settings = load_settings(config_path=config_path, env={})

    assert settings.api_key == "from_config"
    assert settings.model == "gpt-4.1"
    assert settings.reasoning_effort is ReasoningEffort.LOW
    assert settings.fs_mode is FsMode.UNRESTRICTED
    assert settings.approval_policy is ApprovalPolicy.ALWAYS
    assert settings.log_level is LogLevel.DEBUG


def test_env_overrides_config(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        """
[auth]
api_key = "from_config"
"""
    )
    env: Mapping[str, str] = {"OPENAI_API_KEY": "from_env"}

    settings = load_settings(config_path=config_path, env=env)

    assert settings.api_key == "from_env"


def test_cli_overrides_env_and_config(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        """
[model]
id = "config-model"

[runtime]
approval_policy = "on-request"
"""
    )
    env = {"OPENAI_API_KEY": "env_key"}
    cli = {"model": "cli-model", "approval_policy": "always"}

    settings = load_settings(config_path=config_path, env=env, cli_overrides=cli)

    assert settings.model == "cli-model"
    assert settings.approval_policy is ApprovalPolicy.ALWAYS
    assert settings.api_key == "env_key"


def test_precedence_applies_across_all_fields(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        """
[auth]
api_key = "config_key"

[model]
id = "config-model"
reasoning_effort = "low"

[runtime]
fs_mode = "unrestricted"
approval_policy = "never"

[logging]
log_level = "debug"
"""
    )

    env = {"OPENAI_API_KEY": "env_key", "LOG_LEVEL": "info"}
    cli = {"model": "cli-model", "fs_mode": "restricted", "log_level": "warning"}

    settings = load_settings(config_path=config_path, env=env, cli_overrides=cli)

    assert settings.api_key == "env_key"
    assert settings.model == "cli-model"
    assert settings.reasoning_effort is ReasoningEffort.LOW
    assert settings.fs_mode is FsMode.RESTRICTED
    assert settings.approval_policy is ApprovalPolicy.NEVER
    assert settings.log_level is LogLevel.WARNING


def test_create_if_missing_sets_permissions(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"

    settings = load_settings(config_path=config_path, env={}, create_if_missing=True)

    assert settings.model == "gpt-4.1-mini"
    assert config_path.exists()
    mode = config_path.stat().st_mode & 0o777
    assert mode == 0o600


def test_existing_permissions_are_corrected(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text("\n")
    config_path.chmod(0o644)

    load_settings(config_path=config_path, env={})

    mode = config_path.stat().st_mode & 0o777
    assert mode == 0o600


def test_write_config_round_trip(tmp_path: Path) -> None:
    config_path = tmp_path / "nested" / "config.toml"
    settings = Settings(
        api_key="token",
        model="gpt-4.1",
        reasoning_effort=ReasoningEffort.HIGH,
        fs_mode=FsMode.UNRESTRICTED,
        approval_policy=ApprovalPolicy.ALWAYS,
        log_level=LogLevel.DEBUG,
    )

    written_path = write_config(settings, config_path)

    assert written_path == config_path
    assert written_path.exists()
    mode = written_path.stat().st_mode & 0o777
    assert mode == 0o600

    reloaded = load_settings(config_path=config_path, env={})

    assert reloaded == settings


def test_write_config_omits_auth_when_missing(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    settings = Settings(api_key=None)

    write_config(settings, config_path)

    content = config_path.read_text()
    assert "[auth]" not in content

    reloaded = tomllib.load(config_path.open("rb"))
    assert "auth" not in reloaded
