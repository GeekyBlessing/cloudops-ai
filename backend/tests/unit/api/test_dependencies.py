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


def test_dynamodb_disabled_returns_shared_in_memory_repository() -> None:
    from cloudops_ai.api.dependencies import get_incident_repository
    from cloudops_ai.repositories.in_memory_incident_repository import InMemoryIncidentRepository

    settings = Settings(use_dynamodb=False)
    repo = get_incident_repository(settings)
    assert isinstance(repo, InMemoryIncidentRepository)


def test_dynamodb_enabled_returns_dynamodb_repository() -> None:
    """use_dynamodb=True is the untested branch -- boto3 resource
    construction is lazy (no network call happens just from building the
    client), so this is safe to exercise without moto or a live endpoint.
    """
    from cloudops_ai.api.dependencies import get_incident_repository
    from cloudops_ai.repositories.dynamodb_incident_repository import DynamoDBIncidentRepository

    settings = Settings(
        use_dynamodb=True,
        dynamodb_table_incidents="cloudops-ai-incidents-test",
        aws_region="us-east-1",
    )
    repo = get_incident_repository(settings)
    assert isinstance(repo, DynamoDBIncidentRepository)


def test_dynamodb_enabled_reuses_cached_instance() -> None:
    """Mirrors test_live_mode_reuses_the_same_cached_instance above -- the
    module-level singleton should not be rebuilt (and therefore not
    re-establish a boto3 resource) on every call within the same process.
    """
    from cloudops_ai.api.dependencies import get_incident_repository

    settings = Settings(
        use_dynamodb=True,
        dynamodb_table_incidents="cloudops-ai-incidents-test",
        aws_region="us-east-1",
    )
    first = get_incident_repository(settings)
    second = get_incident_repository(settings)
    assert first is second


def test_real_aws_disabled_returns_shared_mock_gateway() -> None:
    from cloudops_ai.adapters.mock.mock_aws_gateway import MockAWSGateway
    from cloudops_ai.api.dependencies import get_aws_tools

    settings = Settings(use_real_aws=False)
    tools = get_aws_tools(settings)
    assert isinstance(tools, MockAWSGateway)


def test_real_aws_enabled_returns_boto3_gateway() -> None:
    """use_real_aws=True is the untested branch, mirroring
    get_mutating_aws_tools' live-mode test above -- same lazy-construction
    reasoning applies (boto3 client creation doesn't require reachable
    credentials or a live endpoint).
    """
    from cloudops_ai.api.dependencies import get_aws_tools
    from cloudops_ai.tools.readonly.boto3_aws_gateway import Boto3AWSGateway

    settings = Settings(use_real_aws=True, aws_region="us-east-1")
    tools = get_aws_tools(settings)
    assert isinstance(tools, Boto3AWSGateway)


def test_real_aws_enabled_reuses_cached_instance() -> None:
    from cloudops_ai.api.dependencies import get_aws_tools

    settings = Settings(use_real_aws=True, aws_region="us-east-1")
    first = get_aws_tools(settings)
    second = get_aws_tools(settings)
    assert first is second


def test_no_llm_provider_configured_returns_fallback_chat_model() -> None:
    """The honest, zero-credentials fallback path."""
    from langchain_core.language_models.fake_chat_models import FakeListChatModel

    from cloudops_ai.api.dependencies import get_chat_model

    settings = Settings(anthropic_api_key=None, openai_api_key=None)
    model = get_chat_model(settings)
    assert isinstance(model, FakeListChatModel)


def test_fallback_chat_model_is_cached() -> None:
    """@lru_cache with no arguments -- must return the exact same instance
    every call, not just an equal one.
    """
    from cloudops_ai.api.dependencies import _fallback_chat_model

    first = _fallback_chat_model()
    second = _fallback_chat_model()
    assert first is second


def test_fallback_chat_model_has_two_canned_responses() -> None:
    from cloudops_ai.api.dependencies import _fallback_chat_model

    model = _fallback_chat_model()
    assert len(model.responses) == 2
    assert "unknown" in model.responses[0]


def test_anthropic_configured_without_package_raises_runtime_error() -> None:
    """langchain-anthropic is deliberately not a dependency of this project
    yet (see pyproject.toml) -- this genuinely exercises the ImportError
    path, not a mocked one.
    """
    import pytest

    from cloudops_ai.api.dependencies import get_chat_model

    settings = Settings(anthropic_api_key="fake-key-for-test")
    with pytest.raises(RuntimeError, match="langchain-anthropic isn't installed"):
        get_chat_model(settings)


def test_openai_configured_without_package_raises_runtime_error() -> None:
    """Same reasoning as the Anthropic test above -- langchain-openai is
    genuinely absent, not mocked away.
    """
    import pytest

    from cloudops_ai.api.dependencies import get_chat_model

    settings = Settings(anthropic_api_key=None, openai_api_key="fake-key-for-test")
    with pytest.raises(RuntimeError, match="langchain-openai isn't installed"):
        get_chat_model(settings)


def test_anthropic_is_checked_before_openai() -> None:
    """If both are configured, Anthropic wins -- confirmed by checking
    which provider's ImportError fires when both keys are set.
    """
    import pytest

    from cloudops_ai.api.dependencies import get_chat_model

    settings = Settings(anthropic_api_key="fake-anthropic-key", openai_api_key="fake-openai-key")
    with pytest.raises(RuntimeError, match="langchain-anthropic isn't installed"):
        get_chat_model(settings)
