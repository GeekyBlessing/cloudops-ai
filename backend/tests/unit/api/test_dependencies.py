"""Unit tests for api/dependencies.py's mode-switching logic.

get_mutating_aws_tools() is the single highest-stakes function in the
codebase -- it's the only place that decides whether a request can ever
reach a real, AWS-mutating boto3 call. These tests exist purely to pin
down that switching behavior directly, independent of the full FastAPI
dependency-injection machinery exercised elsewhere (test_remediation_router.py).
"""

from __future__ import annotations

from cloudops_ai.api.dependencies import get_mutating_aws_tools
from cloudops_ai.core.config import Settings
from cloudops_ai.domain.enums import RemediationMode
from cloudops_ai.tools.dry_run.dry_run_adapter import DryRunAWSTools
from cloudops_ai.tools.mutating.boto3_mutating_gateway import Boto3MutatingAWSGateway


def test_dry_run_mode_returns_dry_run_adapter() -> None:
    settings = Settings(remediation_mode=RemediationMode.DRY_RUN)

    tools = get_mutating_aws_tools(settings)

    assert isinstance(tools, DryRunAWSTools)


def test_default_settings_returns_dry_run_adapter() -> None:
    """The dataclass default (no REMEDIATION_MODE env var set at all) must
    resolve to dry-run -- the fail-safe path if an operator forgets to set
    anything.
    """
    settings = Settings()

    tools = get_mutating_aws_tools(settings)

    assert isinstance(tools, DryRunAWSTools)


def test_live_mode_returns_real_boto3_adapter() -> None:
    settings = Settings(remediation_mode=RemediationMode.LIVE, aws_region="us-east-1")

    tools = get_mutating_aws_tools(settings)

    assert isinstance(tools, Boto3MutatingAWSGateway)


def test_live_mode_reuses_the_same_cached_instance() -> None:
    """The module-level singleton should not be rebuilt (and therefore not
    re-establish AWS clients) on every call within the same process.
    """
    settings = Settings(remediation_mode=RemediationMode.LIVE, aws_region="us-east-1")

    first = get_mutating_aws_tools(settings)
    second = get_mutating_aws_tools(settings)

    assert first is second
