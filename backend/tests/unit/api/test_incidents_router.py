"""Integration-style tests for the /incidents router, run against a real
FastAPI TestClient with dependencies overridden to use test doubles.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient
from langchain_core.language_models.fake_chat_models import FakeListChatModel

from cloudops_ai.adapters.mock.mock_aws_gateway import MockAWSGateway
from cloudops_ai.api.dependencies import get_aws_tools, get_chat_model, get_incident_repository
from cloudops_ai.main import create_app
from cloudops_ai.repositories.in_memory_incident_repository import InMemoryIncidentRepository


def _build_test_client(
    gateway: MockAWSGateway, chat_model: FakeListChatModel, repo: InMemoryIncidentRepository
) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_aws_tools] = lambda: gateway
    app.dependency_overrides[get_chat_model] = lambda: chat_model
    app.dependency_overrides[get_incident_repository] = lambda: repo
    return TestClient(app)


def test_health_endpoint() -> None:
    client = _build_test_client(MockAWSGateway(), FakeListChatModel(responses=["{}"]), InMemoryIncidentRepository())
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_create_incident_runs_full_pipeline_and_proposes_remediation() -> None:
    instance_arn = "arn:aws:ec2:us-east-1:123456789012:instance/i-0abcd1234"
    gateway = MockAWSGateway()
    now = datetime.now(timezone.utc)
    gateway.seed_metric_data(
        namespace="AWS/EC2",
        metric_name="CPUUtilization",
        dimensions={"InstanceId": "i-0abcd1234"},
        datapoints=[{"Timestamp": now.isoformat(), "Average": 97.0}],
    )
    chat_model = FakeListChatModel(
        responses=[
            '{"incident_type": "ec2_high_cpu", "severity": "high"}',
            "Sustained high CPU with no other evidence of a transient spike.",
        ]
    )
    repo = InMemoryIncidentRepository()
    client = _build_test_client(gateway, chat_model, repo)

    response = client.post("/incidents", json={"instance_arn": instance_arn})

    assert response.status_code == 201
    body = response.json()
    assert body["incident_type"] == "ec2_high_cpu"
    assert body["severity"] == "high"
    assert body["proposed_remediation"]["actions"][0]["action_name"] == "reboot_instance"
    assert body["remediation_status"] == "awaiting_approval"


def test_get_incident_returns_404_for_unknown_id() -> None:
    client = _build_test_client(MockAWSGateway(), FakeListChatModel(responses=["{}"]), InMemoryIncidentRepository())
    response = client.get("/incidents/does-not-exist")
    assert response.status_code == 404


def test_list_then_get_incident_round_trip() -> None:
    instance_arn = "arn:aws:ec2:us-east-1:123456789012:instance/i-0abcd9999"
    gateway = MockAWSGateway()
    chat_model = FakeListChatModel(
        responses=['{"incident_type": "unknown", "severity": "low"}', "Placeholder rationale."]
    )
    repo = InMemoryIncidentRepository()
    client = _build_test_client(gateway, chat_model, repo)

    create_response = client.post("/incidents", json={"instance_arn": instance_arn})
    incident_id = create_response.json()["incident_id"]

    list_response = client.get("/incidents")
    assert any(item["incident_id"] == incident_id for item in list_response.json())

    get_response = client.get(f"/incidents/{incident_id}")
    assert get_response.status_code == 200
    assert get_response.json()["incident_id"] == incident_id
