import pytest

from lincona.config import ApprovalPolicy
from lincona.tools.approval import ApprovalRequiredError, approval_guard


def test_never_allows() -> None:
    approval_guard(ApprovalPolicy.NEVER, "shell")


def test_on_request_allows() -> None:
    with pytest.raises(ApprovalRequiredError):
        approval_guard(ApprovalPolicy.ON_REQUEST, "apply_patch")


def test_always_blocks() -> None:
    with pytest.raises(ApprovalRequiredError):
        approval_guard(ApprovalPolicy.ALWAYS, "apply_patch")
