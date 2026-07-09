"""FastAPI dependency providers.

Every dependency here is a function FastAPI calls per-request (or once, for
the `lru_cache`d ones) -- this is where "which concrete adapter is bound to
which interface" is decided for the running application, mirroring how
agents/graph.py does the same thing for the agent runtime itself.
"""

from __future__ import annotations

from functools import lru_cache

from fastapi import Depends
from langchain_core.language_models import BaseChatModel
from langchain_core.language_models.fake_chat_models import FakeListChatModel

from cloudops_ai.adapters.mock.mock_aws_gateway import MockAWSGateway
from cloudops_ai.core.config import Settings, get_settings
from cloudops_ai.domain.enums import RemediationMode
from cloudops_ai.repositories.dynamodb_incident_repository import DynamoDBIncidentRepository
from cloudops_ai.repositories.in_memory_incident_repository import InMemoryIncidentRepository
from cloudops_ai.repositories.interfaces import IIncidentRepository
from cloudops_ai.tools.dry_run.dry_run_adapter import DryRunAWSTools
from cloudops_ai.tools.interfaces import IMutatingAWSTools, IReadOnlyAWSTools
from cloudops_ai.tools.mutating.boto3_mutating_gateway import Boto3MutatingAWSGateway
from cloudops_ai.tools.readonly.boto3_aws_gateway import Boto3AWSGateway

_shared_repository = InMemoryIncidentRepository()
_shared_aws_gateway = MockAWSGateway()
_shared_dry_run_tools = DryRunAWSTools()

_dynamodb_repository: DynamoDBIncidentRepository | None = None
_real_aws_gateway: Boto3AWSGateway | None = None
_real_mutating_gateway: Boto3MutatingAWSGateway | None = None


def get_incident_repository(settings: Settings = Depends(get_settings)) -> IIncidentRepository:
    """In-memory by default -- zero setup, data lost on restart. Set
    CLOUDOPS_USE_DYNAMODB=true (plus CLOUDOPS_DYNAMODB_ENDPOINT_URL for
    DynamoDB Local) to switch to the real, persistent repository. Routers
    depend on IIncidentRepository, never on either concrete class, so this
    is the only place that decision gets made.
    """
    global _dynamodb_repository

    if not settings.use_dynamodb:
        return _shared_repository

    if _dynamodb_repository is None:
        _dynamodb_repository = DynamoDBIncidentRepository(
            table_name=settings.dynamodb_table_incidents,
            region=settings.aws_region,
            endpoint_url=settings.dynamodb_endpoint_url,
        )
    return _dynamodb_repository


def get_aws_tools(settings: Settings = Depends(get_settings)) -> IReadOnlyAWSTools:
    """Mock gateway by default -- zero setup, zero AWS cost, zero blast
    radius. Set CLOUDOPS_USE_REAL_AWS=true to switch to Boto3AWSGateway,
    which makes real read-only calls against whatever account the process's
    credentials resolve to (instance role in ECS, environment/SSO locally).
    Agents depend on IReadOnlyAWSTools, never on either concrete class, so
    this is the only place that decision gets made.
    """
    global _real_aws_gateway

    if not settings.use_real_aws:
        return _shared_aws_gateway

    if _real_aws_gateway is None:
        _real_aws_gateway = Boto3AWSGateway(region=settings.aws_region)
    return _real_aws_gateway


def get_mutating_aws_tools(settings: Settings = Depends(get_settings)) -> IMutatingAWSTools:
    """Dry-run by default -- zero setup, zero blast radius, every action
    just logged. REMEDIATION_MODE=live switches to Boto3MutatingAWSGateway,
    which makes real mutating calls against whatever account the process's
    credentials resolve to.

    This is the single most safety-sensitive line in the entire codebase --
    it's the only place a real AWS mutation becomes reachable at all. Two
    things are deliberately true about it: (1) the default is dry-run, not
    live, so a missing/misconfigured env var fails safe; (2) even when this
    returns the real adapter, nothing downstream can call it without first
    passing RemediationPlan.can_execute_live() (HMAC-signed human approval)
    in the Remediation Executor -- see agents/remediation_executor.py and
    domain/models/remediation.py. This function alone does not grant the
    ability to mutate AWS; it's one of two independent gates that both have
    to open.
    """
    global _real_mutating_gateway

    if settings.remediation_mode != RemediationMode.LIVE:
        return _shared_dry_run_tools

    if _real_mutating_gateway is None:
        _real_mutating_gateway = Boto3MutatingAWSGateway(region=settings.aws_region)
    return _real_mutating_gateway


@lru_cache
def _fallback_chat_model() -> BaseChatModel:
    """Used when no LLM provider is configured, so the API is runnable --
    and honestly labeled -- with zero credentials. Every incident gets
    classified as unknown/low with a placeholder rationale instead of the
    request crashing outright.
    """
    return FakeListChatModel(
        responses=[
            '{"incident_type": "unknown", "severity": "low"}',
            "No LLM provider is configured (set CLOUDOPS_ANTHROPIC_API_KEY or "
            "CLOUDOPS_OPENAI_API_KEY). This is a placeholder rationale from the fallback chat model.",
        ]
    )


def get_chat_model(settings: Settings = Depends(get_settings)) -> BaseChatModel:
    """Provider-agnostic chat model factory.

    Real provider wiring is intentionally minimal here -- this becomes
    adapters/llm/provider.py in a later build step, likely with retries,
    timeouts, and per-agent model selection. For now: Anthropic if
    configured, else OpenAI if configured, else the honest fallback above.
    """
    if settings.anthropic_api_key:
        try:
            from langchain_anthropic import ChatAnthropic
        except ImportError as exc:
            raise RuntimeError(
                "CLOUDOPS_ANTHROPIC_API_KEY is set but langchain-anthropic isn't installed. "
                "Add it to pyproject.toml's dependencies and run `uv sync` again."
            ) from exc
        return ChatAnthropic(model=settings.anthropic_model, api_key=settings.anthropic_api_key)

    if settings.openai_api_key:
        try:
            from langchain_openai import ChatOpenAI
        except ImportError as exc:
            raise RuntimeError(
                "CLOUDOPS_OPENAI_API_KEY is set but langchain-openai isn't installed. "
                "Add it to pyproject.toml's dependencies and run `uv sync` again."
            ) from exc
        return ChatOpenAI(model=settings.openai_model, api_key=settings.openai_api_key)

    return _fallback_chat_model()
