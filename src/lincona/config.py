"""Configuration models and enums for Lincona.

Single source of truth for settings, model capabilities, and defaults.
"""

from __future__ import annotations

import os
import stat
import tomllib
from collections.abc import Mapping
from enum import Enum
from pathlib import Path
from typing import Any, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator


class FsMode(str, Enum):
    RESTRICTED = "restricted"
    UNRESTRICTED = "unrestricted"


class ApprovalPolicy(str, Enum):
    NEVER = "never"
    ON_REQUEST = "on-request"
    ALWAYS = "always"


class LogLevel(str, Enum):
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class ReasoningEffort(str, Enum):
    NONE = "none"
    MINIMAL = "minimal"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Verbosity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ModelCapabilities(BaseModel):
    """Resolved Lincona settings with per-model capabilities."""

    model_config = ConfigDict(frozen=True, validate_default=True, extra="forbid")

    reasoning_effort: tuple[ReasoningEffort, ...] = Field(default_factory=tuple)
    default_reasoning: ReasoningEffort | None = None
    verbosity: tuple[Verbosity, ...] = Field(default_factory=tuple)
    default_verbosity: Verbosity | None = None

    @field_validator("reasoning_effort")
    @classmethod
    def _validate_reasoning(cls, value: tuple[ReasoningEffort, ...]) -> tuple[ReasoningEffort, ...]:
        if value and len(set(value)) != len(value):
            raise ValueError("reasoning_effort entries must be unique")
        return value

    @field_validator("verbosity")
    @classmethod
    def _validate_verbosity(cls, value: tuple[Verbosity, ...]) -> tuple[Verbosity, ...]:
        if value and len(set(value)) != len(value):
            raise ValueError("verbosity entries must be unique")
        return value

    @field_validator("default_reasoning")
    @classmethod
    def _validate_default_reasoning(cls, value: ReasoningEffort | None, info: Any) -> ReasoningEffort | None:
        if value is None:
            return None
        allowed = info.data.get("reasoning_effort", ())
        if value not in allowed:
            raise ValueError("default_reasoning must be in reasoning_effort")
        return value

    @field_validator("default_verbosity")
    @classmethod
    def _validate_default_verbosity(cls, value: Verbosity | None, info: Any) -> Verbosity | None:
        if value is None:
            return None
        allowed = info.data.get("verbosity", ())
        if value not in allowed:
            raise ValueError("default_verbosity must be in verbosity")
        return value


SEED_MODEL_ID = "gpt-5.1-codex-mini"
SEED_CAPABILITIES = ModelCapabilities(
    reasoning_effort=(
        ReasoningEffort.NONE,
        ReasoningEffort.MINIMAL,
        ReasoningEffort.LOW,
        ReasoningEffort.MEDIUM,
        ReasoningEffort.HIGH,
    ),
    default_reasoning=ReasoningEffort.NONE,
    verbosity=(Verbosity.LOW, Verbosity.MEDIUM, Verbosity.HIGH),
    default_verbosity=Verbosity.MEDIUM,
)


def _default_models() -> dict[str, ModelCapabilities]:
    return {SEED_MODEL_ID: SEED_CAPABILITIES}


class Settings(BaseModel):
    """Resolved Lincona settings with per-model capabilities."""

    model_config = ConfigDict(frozen=True, validate_default=True, extra="forbid")

    api_key: str | None = None
    model: str = SEED_MODEL_ID
    reasoning_effort: ReasoningEffort | None = SEED_CAPABILITIES.default_reasoning
    verbosity: Verbosity | None = SEED_CAPABILITIES.default_verbosity
    models: dict[str, ModelCapabilities] = Field(default_factory=_default_models)
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

    @field_validator("reasoning_effort")
    @classmethod
    def _validate_reasoning_value(cls, value: ReasoningEffort | None) -> ReasoningEffort | None:
        return value

    @field_validator("verbosity")
    @classmethod
    def _validate_verbosity_value(cls, value: Verbosity | None) -> Verbosity | None:
        return value


DEFAULT_CONFIG_PATH = Path.home() / ".lincona" / "config.toml"
EXPECTED_FILE_MODE = stat.S_IRUSR | stat.S_IWUSR  # 0o600

SEED_MODEL_ID = "gpt-5.1-codex-mini"
SEED_CAPABILITIES = ModelCapabilities(
    reasoning_effort=(
        ReasoningEffort.NONE,
        ReasoningEffort.MINIMAL,
        ReasoningEffort.LOW,
        ReasoningEffort.MEDIUM,
        ReasoningEffort.HIGH,
    ),
    default_reasoning=ReasoningEffort.NONE,
    verbosity=(Verbosity.LOW, Verbosity.MEDIUM, Verbosity.HIGH),
    default_verbosity=Verbosity.MEDIUM,
)


def load_settings(
    cli_overrides: Mapping[str, Any] | None = None,
    env: Mapping[str, str] | None = None,
    config_path: Path | str | None = None,
    *,
    create_if_missing: bool = False,
) -> Settings:
    env = env or os.environ
    cli_overrides = cli_overrides or {}
    path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH
    path.parent.mkdir(parents=True, exist_ok=True)

    created_new = False
    if not path.exists() and create_if_missing:
        _write_seed_config(path)
        created_new = True

    config_data: dict[str, Any] = {}
    if path.exists():
        _ensure_permissions(path)
        config_data = _read_toml(path)

    defaults = _seed_settings()

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
    )

    verbosity = _first_value(
        _clean_str(cli_overrides.get("verbosity")),
        _clean_str(_get_config_value(config_data, "model", "verbosity")),
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

    models_section = _parse_models(config_data.get("models", {}))
    if not models_section:
        models_section = _default_models()
    if model not in models_section:
        if model.startswith("gpt-5"):
            models_section[model] = SEED_CAPABILITIES
        else:
            raise SystemExit(f"model '{model}' not defined in [models.{model}]")

    reasoning_effort = _coerce_reasoning(reasoning_effort, None)
    verbosity = _coerce_verbosity(verbosity, None)
    fs_mode_enum = _coerce_enum(fs_mode, FsMode, FsMode.RESTRICTED)
    fs_mode_val = cast(FsMode, fs_mode_enum or FsMode.RESTRICTED)

    approval_policy_enum = _coerce_enum(approval_policy, ApprovalPolicy, ApprovalPolicy.ON_REQUEST)
    approval_policy_val = cast(ApprovalPolicy, approval_policy_enum or ApprovalPolicy.ON_REQUEST)

    log_level_enum = _coerce_enum(log_level, LogLevel, LogLevel.INFO)
    log_level_val = cast(LogLevel, log_level_enum or LogLevel.INFO)

    selected_cap = models_section[model]
    applied_reasoning = reasoning_effort or selected_cap.default_reasoning
    if applied_reasoning is None and selected_cap.reasoning_effort:
        applied_reasoning = selected_cap.reasoning_effort[0]
    if applied_reasoning and applied_reasoning not in selected_cap.reasoning_effort:
        raise SystemExit(f"reasoning '{applied_reasoning.value}' not supported for model {model}")

    applied_verbosity = verbosity or selected_cap.default_verbosity
    if applied_verbosity is None and selected_cap.verbosity:
        applied_verbosity = selected_cap.verbosity[0]
    if applied_verbosity:
        if applied_verbosity not in selected_cap.verbosity:
            raise SystemExit(f"verbosity '{applied_verbosity.value}' not supported for model {model}")

    settings = Settings(
        api_key=api_key,
        model=model,
        reasoning_effort=applied_reasoning if isinstance(applied_reasoning, ReasoningEffort) else None,
        verbosity=applied_verbosity if isinstance(applied_verbosity, Verbosity) else None,
        models=models_section,
        fs_mode=fs_mode_val,
        approval_policy=approval_policy_val,
        log_level=log_level_val,
    )

    if created_new:
        write_config(settings, path)
    return settings


def write_config(settings: Settings, config_path: Path | str | None = None) -> Path:
    path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH
    path.parent.mkdir(parents=True, exist_ok=True)

    sections: list[str] = []

    auth_section: dict[str, Any] = {}
    if settings.api_key is not None:
        auth_section["api_key"] = settings.api_key
    _append_section(sections, "auth", auth_section)

    model_section: dict[str, Any] = {"id": settings.model}
    if settings.reasoning_effort is not None:
        model_section["reasoning_effort"] = settings.reasoning_effort.value
    if settings.verbosity is not None:
        model_section["verbosity"] = settings.verbosity.value
    _append_section(sections, "model", model_section)

    if settings.models:
        for model_id, cap in settings.models.items():
            _append_section(
                sections,
                f'models."{model_id}"',
                {
                    "reasoning_effort": [v.value for v in cap.reasoning_effort],
                    "default_reasoning": cap.default_reasoning.value if cap.default_reasoning else None,
                    "verbosity": [v.value for v in cap.verbosity],
                    "default_verbosity": cap.default_verbosity.value if cap.default_verbosity else None,
                },
            )

    runtime_section = {
        "fs_mode": settings.fs_mode.value,
        "approval_policy": settings.approval_policy.value,
    }
    _append_section(sections, "runtime", runtime_section)

    logging_section = {"log_level": settings.log_level.value}
    _append_section(sections, "logging", logging_section)

    content = "\n\n".join(filter(None, sections)) + "\n"
    path.write_text(content, encoding="utf-8")
    path.chmod(EXPECTED_FILE_MODE)
    return path


def _write_seed_config(path: Path) -> None:
    seed_settings = _seed_settings()
    write_config(seed_settings, path)


def _seed_settings() -> Settings:
    return Settings(
        api_key=None,
        model=SEED_MODEL_ID,
        reasoning_effort=SEED_CAPABILITIES.default_reasoning,
        verbosity=SEED_CAPABILITIES.default_verbosity,
        models={SEED_MODEL_ID: SEED_CAPABILITIES},
        fs_mode=FsMode.RESTRICTED,
        approval_policy=ApprovalPolicy.ON_REQUEST,
        log_level=LogLevel.INFO,
    )


def _ensure_permissions(path: Path) -> None:
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


def _coerce_reasoning(
    value: Any, default: ReasoningEffort | None = None
) -> ReasoningEffort | None:
    if value is None:
        return default
    if isinstance(value, ReasoningEffort):
        return value
    if isinstance(value, str):
        try:
            return ReasoningEffort(value)
        except Exception:
            return default
    return default


def _coerce_verbosity(
    value: Any, default: Verbosity | None = None
) -> Verbosity | None:
    if value is None:
        return default
    if isinstance(value, Verbosity):
        return value
    if isinstance(value, str):
        try:
            return Verbosity(value)
        except Exception:
            return default
    return default


def _coerce_enum(value: Any, enum_cls: type[Enum], default: Enum | None = None) -> Enum | None:
    if value is None:
        return default
    if isinstance(value, enum_cls):
        return value
    if isinstance(value, str):
        try:
            return enum_cls(value)
        except Exception:
            return default
    return default


def _parse_models(section: Any) -> dict[str, ModelCapabilities]:
    if not isinstance(section, dict):
        return {}
    models: dict[str, ModelCapabilities] = {}
    for key, value in section.items():
        if not isinstance(value, dict):
            continue
        reasoning_vals = value.get("reasoning_effort", [])
        verbosity_vals = value.get("verbosity", [])
        cap = ModelCapabilities(
            reasoning_effort=tuple(ReasoningEffort(v) for v in reasoning_vals),
            default_reasoning=_coerce_reasoning(value.get("default_reasoning")),
            verbosity=tuple(Verbosity(v) for v in verbosity_vals),
            default_verbosity=_coerce_verbosity(value.get("default_verbosity")),
        )
        models[key] = cap
    return models


def _append_section(parts: list[str], name: str, values: Mapping[str, Any]) -> None:
    filtered = {k: v for k, v in values.items() if v is not None and v != [] and v != ()}
    if not filtered:
        return
    lines = [f"[{name}]"]
    for key, val in filtered.items():
        if isinstance(val, str):
            escaped = val.replace('"', '\\"')
            lines.append(f'{key} = "{escaped}"')
        elif isinstance(val, list | tuple):
            rendered_items = []
            for item in val:
                if isinstance(item, str):
                    rendered_items.append(f'"{item.replace(chr(34), "\\\\" + chr(34))}"')
                elif isinstance(item, Enum):
                    rendered_items.append(f'"{item.value}"')
                else:
                    rendered_items.append(str(item))
            joined = ", ".join(rendered_items)
            lines.append(f"{key} = [{joined}]")
        elif isinstance(val, Enum):
            lines.append(f'{key} = "{val.value}"')
        else:
            lines.append(f"{key} = {val}")
    parts.append("\n".join(lines))


__all__ = [
    "Settings",
    "FsMode",
    "ApprovalPolicy",
    "LogLevel",
    "ReasoningEffort",
    "Verbosity",
    "ModelCapabilities",
    "DEFAULT_CONFIG_PATH",
    "load_settings",
    "write_config",
]
