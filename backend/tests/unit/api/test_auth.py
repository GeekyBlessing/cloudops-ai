"""Tests for require_api_key -- the shared-secret gate on /incidents and
/remediation.

Uses app.dependency_overrides[get_settings] rather than environment
variables to control CLOUDOPS_API_KEY per-test, matching how every other
router test in this file overrides its dependencies.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from langchain_core.language_models.fake_chat_models import FakeListChatModel

from cloudops_ai.adapters.mock.mock_aws_gateway import MockAWSGateway
from cloudops_ai.api.dependencies import get_aws_tools, get_chat_model, get_incident_repository
from cloudops_ai.core.config import Settings, get_settings
from cloudops_ai.main import create_app
from cloudops_ai.repositories.in_memory_incident_repository import InMemoryIncidentRepository


def _build_test_client(settings: Settings) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_aws_tools] = lambda: MockAWSGateway()
    app.dependency_overrides[get_chat_model] = lambda: FakeListChatModel(responses=["{}"])
    app.dependency_overrides[get_incident_repository] = lambda: InMemoryIncidentRepository()
    return TestClient(app)


def test_no_api_key_configured_allows_unauthenticated_requests() -> None:
    """The default (api_key=None) -- local dev, zero setup."""
    client = _build_test_client(Settings(api_key=None))

    response = client.get("/incidents")

    assert response.status_code == 200


def test_api_key_configured_rejects_missing_header() -> None:
    client = _build_test_client(Settings(api_key="secret-123"))

    response = client.get("/incidents")

    assert response.status_code == 401
    assert response.json()["detail"] == "Missing or invalid API key"


def test_api_key_configured_rejects_wrong_key() -> None:
    client = _build_test_client(Settings(api_key="secret-123"))

    response = client.get("/incidents", headers={"X-API-Key": "wrong-key"})

    assert response.status_code == 401


def test_api_key_configured_accepts_correct_key() -> None:
    client = _build_test_client(Settings(api_key="secret-123"))

    response = client.get("/incidents", headers={"X-API-Key": "secret-123"})

    assert response.status_code == 200


def test_remediation_router_is_also_protected() -> None:
    """The remediation router is the one that can trigger a real AWS
    mutation -- confirming it's gated independently of /incidents, not
    just assuming the same router config applies.
    """
    client = _build_test_client(Settings(api_key="secret-123"))

    response = client.post("/remediation/some-id/reject")

    assert response.status_code == 401


def test_health_endpoint_is_never_protected() -> None:
    """/health is defined directly on the app, outside both protected
    routers -- an ECS health check has no way to attach a custom header,
    so this must stay open regardless of whether CLOUDOPS_API_KEY is set.
    """
    client = _build_test_client(Settings(api_key="secret-123"))

    response = client.get("/health")

    assert response.status_code == 200
