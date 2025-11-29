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

    with pytest.raises(ValidationError):
        ModelCapabilities(reasoning_effort=(ReasoningEffort.LOW, ReasoningEffort.LOW))

    with pytest.raises(ValidationError):
        ModelCapabilities(verbosity=(Verbosity.LOW, Verbosity.LOW))


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


def test_settings_model_must_not_be_empty() -> None:
    with pytest.raises(ValidationError):
        Settings(model=" ")


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


def test_coercion_helpers_defaults() -> None:
    from lincona.config import _coerce_enum, _coerce_reasoning, _coerce_verbosity, _first_value, _clean_str

    assert _coerce_reasoning("unknown", ReasoningEffort.NONE) == ReasoningEffort.NONE
    assert _coerce_verbosity("unknown", Verbosity.LOW) == Verbosity.LOW
    assert _coerce_enum("missing", ApprovalPolicy, ApprovalPolicy.NEVER) == ApprovalPolicy.NEVER
    assert _first_value(None, None) is None
    assert _clean_str("  ") is None


def test_parse_models_ignores_bad_entries() -> None:
    from lincona.config import _parse_models

    models = _parse_models({"good": {"reasoning_effort": ["none"], "verbosity": ["low"]}, "bad": "oops"})
    assert "good" in models and "bad" not in models


def test_append_section_quotes_and_skips_empty() -> None:
    from lincona.config import _append_section

    parts: list[str] = []
    _append_section(parts, "auth", {})
    _append_section(parts, "logging", {"log_level": LogLevel.DEBUG})
    _append_section(parts, "model", {"id": 'gpt"5'})
    text = "\n\n".join(parts)
    assert 'log_level = "debug"' in text
    assert '\\"' in text  # quotes escaped


def test_ensure_permissions_sets_mode(tmp_path: Path) -> None:
    from lincona.config import _ensure_permissions, EXPECTED_FILE_MODE
    cfg = tmp_path / "f"
    cfg.write_text("x", encoding="utf-8")
    cfg.chmod(0o644)
    _ensure_permissions(cfg)
    assert cfg.stat().st_mode & 0o777 == EXPECTED_FILE_MODE


def test_get_config_value_returns_none_for_non_dict() -> None:
    from lincona.config import _get_config_value

    assert _get_config_value({"section": "not-dict"}, "section", "k") is None


def test_load_settings_reads_existing_file(tmp_path: Path) -> None:
    cfg = tmp_path / "config.toml"
    cfg.write_text("[model]\nid = \"gpt-5.1-codex-mini\"\n", encoding="utf-8")
    settings = load_settings(config_path=cfg, env={})
    assert settings.model == "gpt-5.1-codex-mini"


def test_reasoning_not_supported_raises(tmp_path: Path) -> None:
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        """
[model]
id = "gpt-5.1-codex-mini"
reasoning_effort = "high"

[models."gpt-5.1-codex-mini"]
reasoning_effort = ["none"]
default_reasoning = "none"
verbosity = ["low"]
default_verbosity = "low"
""",
        encoding="utf-8",
    )
    with pytest.raises(SystemExit):
        load_settings(config_path=cfg, env={})


def test_verbosity_not_supported_raises(tmp_path: Path) -> None:
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        """
[model]
id = "gpt-5.1-codex-mini"
verbosity = "high"

[models."gpt-5.1-codex-mini"]
reasoning_effort = ["none"]
default_reasoning = "none"
verbosity = ["low"]
default_verbosity = "low"
""",
        encoding="utf-8",
    )
    with pytest.raises(SystemExit):
        load_settings(config_path=cfg, env={})


def test_write_config_includes_model_sections(tmp_path: Path) -> None:
    cfg = tmp_path / "config.toml"
    settings = Settings(
        api_key="k",
        model="gpt-5.1-codex-mini",
        reasoning_effort=ReasoningEffort.HIGH,
        verbosity=Verbosity.HIGH,
    )
    write_config(settings, cfg)
    text = cfg.read_text()
    assert "[model]" in text and "[runtime]" in text and "approval_policy" in text


def test_append_section_handles_enums_and_numbers() -> None:
    from lincona.config import _append_section

    parts: list[str] = []
    _append_section(parts, "section", {"level": LogLevel.INFO, "nums": [1, 2]})
    rendered = "\n".join(parts)
    assert 'level = "info"' in rendered
    assert "nums = [1, 2]" in rendered


def test_write_config_includes_models_loop(tmp_path: Path) -> None:
    cfg = tmp_path / "config.toml"
    models = {
        "m1": ModelCapabilities(
            reasoning_effort=(ReasoningEffort.NONE,),
            default_reasoning=ReasoningEffort.NONE,
            verbosity=(Verbosity.LOW,),
            default_verbosity=Verbosity.LOW,
        ),
        "m2": ModelCapabilities(
            reasoning_effort=(ReasoningEffort.NONE,),
            default_reasoning=ReasoningEffort.NONE,
            verbosity=(Verbosity.LOW,),
            default_verbosity=Verbosity.LOW,
        ),
    }
    settings = Settings(
        api_key="k",
        model="m1",
        reasoning_effort=ReasoningEffort.NONE,
        verbosity=Verbosity.LOW,
        models=models,
    )
    write_config(settings, cfg)
    text = cfg.read_text()
    assert 'models."m2"' in text
