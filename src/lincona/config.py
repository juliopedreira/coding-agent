"""Configuration models and enums for Lincona.

This module defines the `Settings` model used across the application. It is
immutable, validates enum-backed fields, and carries hard-coded defaults that
are resolved before config/env/CLI precedence is applied in later steps.
"""

from __future__ import annotations

import os
import stat
import tomllib
from collections.abc import Mapping
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator


class FsMode(str, Enum):
    """Filesystem boundary mode."""

    RESTRICTED = "restricted"
    UNRESTRICTED = "unrestricted"


class ApprovalPolicy(str, Enum):
    """User-approval policy for tool execution."""

    NEVER = "never"
    ON_REQUEST = "on-request"
    ALWAYS = "always"


class LogLevel(str, Enum):
    """Logging verbosity."""

    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class ReasoningEffort(str, Enum):
    """Model reasoning effort level."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Settings(BaseModel):
    """Resolved Lincona settings.

    The model is immutable and validates enum-backed fields. Defaults mirror
    the decisions documented in MVP Epic 2.
    """

    model_config = ConfigDict(frozen=True, validate_default=True, extra="forbid")

    api_key: str | None = None
    model: str = "gpt-4.1-mini"
    reasoning_effort: ReasoningEffort = ReasoningEffort.MEDIUM
    fs_mode: FsMode = FsMode.RESTRICTED
    approval_policy: ApprovalPolicy = ApprovalPolicy.ON_REQUEST
    log_level: LogLevel = LogLevel.INFO

    @field_validator("api_key")
    @classmethod
    def _strip_api_key(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped if stripped else None

    @field_validator("model")
    @classmethod
    def _validate_model(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("model cannot be empty")
        return value.strip()


DEFAULT_CONFIG_PATH = Path.home() / ".lincona" / "config.toml"
EXPECTED_FILE_MODE = stat.S_IRUSR | stat.S_IWUSR  # 0o600


def load_settings(
    cli_overrides: Mapping[str, Any] | None = None,
    env: Mapping[str, str] | None = None,
    config_path: Path | str | None = None,
    *,
    create_if_missing: bool = False,
) -> Settings:
    """Load settings with precedence CLI > env > config file > defaults.

    - ``cli_overrides``: typically parsed CLI args, only non-None values apply.
    - ``env``: environment mapping (defaults to ``os.environ``).
    - ``config_path``: override for config location (defaults to ``~/.lincona/config.toml``).
    - ``create_if_missing``: when True, touch the config file with mode 600 if absent.
    """

    env = env or os.environ
    cli_overrides = cli_overrides or {}
    path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH

    # Ensure parent directory exists.
    path.parent.mkdir(parents=True, exist_ok=True)

    config_data: dict[str, Any] = {}
    if path.exists():
        config_data = _read_toml(path)
    elif create_if_missing:
        path.touch(exist_ok=True)
        path.chmod(EXPECTED_FILE_MODE)

    if path.exists():
        _ensure_permissions(path)

    defaults = Settings()

    api_key = _first_value(
        _clean_str(cli_overrides.get("api_key")),
        _clean_str(env.get("OPENAI_API_KEY")),
        _clean_str(_get_config_value(config_data, "auth", "api_key")),
        defaults.api_key,
    )

    model = _first_value(
        _clean_str(cli_overrides.get("model")),
        _clean_str(_get_config_value(config_data, "model", "id")),
        defaults.model,
    )

    reasoning_effort = _first_value(
        _clean_str(cli_overrides.get("reasoning_effort")),
        _clean_str(_get_config_value(config_data, "model", "reasoning_effort")),
        defaults.reasoning_effort,
    )

    fs_mode = _first_value(
        _clean_str(cli_overrides.get("fs_mode")),
        _clean_str(_get_config_value(config_data, "runtime", "fs_mode")),
        defaults.fs_mode,
    )

    approval_policy = _first_value(
        _clean_str(cli_overrides.get("approval_policy")),
        _clean_str(_get_config_value(config_data, "runtime", "approval_policy")),
        defaults.approval_policy,
    )

    log_level = _first_value(
        _clean_str(cli_overrides.get("log_level")),
        _clean_str(_get_config_value(config_data, "logging", "log_level")),
        defaults.log_level,
    )

    return Settings(
        api_key=api_key,
        model=model,
        reasoning_effort=reasoning_effort,
        fs_mode=fs_mode,
        approval_policy=approval_policy,
        log_level=log_level,
    )


def write_config(settings: Settings, config_path: Path | str | None = None) -> Path:
    """Serialize settings to TOML using the documented layout.

    Only non-None values are written. Parent directories are created and file
    permissions are enforced to 600.
    """

    path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH
    path.parent.mkdir(parents=True, exist_ok=True)

    sections: list[str] = []

    auth_section: dict[str, Any] = {}
    if settings.api_key is not None:
        auth_section["api_key"] = settings.api_key
    _append_section(sections, "auth", auth_section)

    model_section = {
        "id": settings.model,
        "reasoning_effort": settings.reasoning_effort.value,
    }
    _append_section(sections, "model", model_section)

    runtime_section = {
        "fs_mode": settings.fs_mode.value,
        "approval_policy": settings.approval_policy.value,
    }
    _append_section(sections, "runtime", runtime_section)

    logging_section = {"log_level": settings.log_level.value}
    _append_section(sections, "logging", logging_section)

    content = "\n\n".join(sections) + "\n"
    path.write_text(content, encoding="utf-8")
    path.chmod(EXPECTED_FILE_MODE)
    return path


def _ensure_permissions(path: Path) -> None:
    """Force config file permissions to 600 (owner read/write)."""

    current_mode = stat.S_IMODE(path.stat().st_mode)
    if current_mode != EXPECTED_FILE_MODE:
        path.chmod(EXPECTED_FILE_MODE)


def _read_toml(path: Path) -> dict[str, Any]:
    with path.open("rb") as handle:
        return tomllib.load(handle)


def _get_config_value(config: Mapping[str, Any], section: str, key: str) -> Any:
    section_data = config.get(section)
    if not isinstance(section_data, dict):
        return None
    return section_data.get(key)


def _clean_str(value: Any) -> Any:
    if isinstance(value, str):
        stripped = value.strip()
        return stripped if stripped else None
    return value


def _first_value(*candidates: Any) -> Any:
    for candidate in candidates:
        if candidate is not None:
            return candidate
    return None


def _append_section(parts: list[str], name: str, values: Mapping[str, Any]) -> None:
    if not values:
        return
    lines = [f"[{name}]"]
    for key, val in values.items():
        if isinstance(val, str):
            escaped = val.replace('"', '\\"')
            lines.append(f'{key} = "{escaped}"')
        else:
            lines.append(f"{key} = {val}")
    parts.append("\n".join(lines))


__all__ = [
    "Settings",
    "FsMode",
    "ApprovalPolicy",
    "LogLevel",
    "ReasoningEffort",
    "DEFAULT_CONFIG_PATH",
    "load_settings",
    "write_config",
]
