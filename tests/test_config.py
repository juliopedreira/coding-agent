import pytest
from pydantic import ValidationError

from lincona.config import (
    ApprovalPolicy,
    FsMode,
    LogLevel,
    ReasoningEffort,
    Settings,
)


def test_settings_defaults() -> None:
    settings = Settings()

    assert settings.api_key is None
    assert settings.model == "gpt-4.1-mini"
    assert settings.reasoning_effort is ReasoningEffort.MEDIUM
    assert settings.fs_mode is FsMode.RESTRICTED
    assert settings.approval_policy is ApprovalPolicy.ON_REQUEST
    assert settings.log_level is LogLevel.WARNING


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
