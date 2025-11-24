"""Approval guard for mutating tools."""

from __future__ import annotations

from lincona.config import ApprovalPolicy


class ApprovalRequiredError(Exception):
    """Raised when approval policy blocks execution."""


def approval_guard(policy: ApprovalPolicy, tool_name: str) -> None:
    """Guard mutating tools based on approval policy."""

    if policy == ApprovalPolicy.NEVER:
        return
    if policy in (ApprovalPolicy.ALWAYS, ApprovalPolicy.ON_REQUEST):
        raise ApprovalRequiredError(f"approval required for tool {tool_name}")
    # fallback: allow


__all__ = ["approval_guard", "ApprovalRequiredError"]
