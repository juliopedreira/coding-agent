"""Configuration models and enums for Lincona.

This module defines the `Settings` model used across the application. It is
immutable, validates enum-backed fields, and carries hard-coded defaults that
are resolved before config/env/CLI precedence is applied in later steps.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

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

    api_key: Optional[str] = None
    model: str = "gpt-4.1-mini"
    reasoning_effort: ReasoningEffort = ReasoningEffort.MEDIUM
    fs_mode: FsMode = FsMode.RESTRICTED
    approval_policy: ApprovalPolicy = ApprovalPolicy.ON_REQUEST
    log_level: LogLevel = LogLevel.WARNING

    @field_validator("api_key")
    @classmethod
    def _strip_api_key(cls, value: Optional[str]) -> Optional[str]:
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


__all__ = [
    "Settings",
    "FsMode",
    "ApprovalPolicy",
    "LogLevel",
    "ReasoningEffort",
]
