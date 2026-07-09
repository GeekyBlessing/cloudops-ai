"""Integration-style tests for the /remediation router -- these prove the
whole loop end-to-end: create an incident via /incidents (which proposes a
plan), approve it via /remediation/{id}/approve, and confirm AWS (the mock
dry-run adapter) actually got called, or reject it and confirm it didn't.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient
from langchain_core.language_models.fake_chat_models import FakeListChatModel

from cloudops_ai.adapters.mock.mock_aws_gateway import MockAWSGateway
from cloudops_ai.api.dependencies import (
    get_aws_tools,
    get_chat_model,
    get_incident_repository,
    get_mutating_aws_tools,
)
from cloudops_ai.main import create_app
from cloudops_ai.repositories.in_memory_incident_repository import InMemoryIncidentRepository
from cloudops_ai.tools.dry_run.dry_run_adapter import DryRunAWSTools


def _build_test_client(gateway, chat_model, repo, mutating_tools):
    app = create_app()
    app.dependency_overrides[get_aws_tools] = lambda: gateway
    app.dependency_overrides[get_chat_model] = lambda: chat_model
    app.dependency_overrides[get_incident_repository] = lambda: repo
    app.dependency_overrides[get_mutating_aws_tools] = lambda: mutating_tools
    return TestClient(app)


def _create_high_cpu_incident(client: TestClient, instance_arn: str) -> str:
    response = client.post("/incidents", json={"instance_arn": instance_arn})
    assert response.status_code == 201
    return response.json()["incident_id"]


def test_approve_runs_the_remediation_and_updates_status() -> None:
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
    dry_run_tools = DryRunAWSTools()
    client = _build_test_client(gateway, chat_model, repo, dry_run_tools)

    incident_id = _create_high_cpu_incident(client, instance_arn)

    response = client.post(f"/remediation/{incident_id}/approve", json={"approved_by": "toriola@example.com"})

    assert response.status_code == 200
    body = response.json()
    assert body["remediation_status"] == "verified"
    assert body["proposed_remediation"]["status"] == "verified"
    assert body["proposed_remediation"]["approval"]["approved_by"] == "toriola@example.com"
    assert dry_run_tools.actions_logged == [{"action": "reboot_instance", "instance_id": "i-0abcd1234"}]


def test_reject_marks_rejected_without_touching_aws() -> None:
    instance_arn = "arn:aws:ec2:us-east-1:123456789012:instance/i-0abcd5678"
    gateway = MockAWSGateway()
    now = datetime.now(timezone.utc)
    gateway.seed_metric_data(
        namespace="AWS/EC2",
        metric_name="CPUUtilization",
        dimensions={"InstanceId": "i-0abcd5678"},
        datapoints=[{"Timestamp": now.isoformat(), "Average": 97.0}],
    )
    chat_model = FakeListChatModel(
        responses=['{"incident_type": "ec2_high_cpu", "severity": "high"}', "Sustained high CPU."]
    )
    repo = InMemoryIncidentRepository()
    dry_run_tools = DryRunAWSTools()
    client = _build_test_client(gateway, chat_model, repo, dry_run_tools)

    incident_id = _create_high_cpu_incident(client, instance_arn)

    response = client.post(f"/remediation/{incident_id}/reject")

    assert response.status_code == 200
    body = response.json()
    assert body["remediation_status"] == "rejected"
    assert dry_run_tools.actions_logged == []


def test_approve_twice_returns_conflict() -> None:
    instance_arn = "arn:aws:ec2:us-east-1:123456789012:instance/i-0abcd9999"
    gateway = MockAWSGateway()
    now = datetime.now(timezone.utc)
    gateway.seed_metric_data(
        namespace="AWS/EC2",
        metric_name="CPUUtilization",
        dimensions={"InstanceId": "i-0abcd9999"},
        datapoints=[{"Timestamp": now.isoformat(), "Average": 97.0}],
    )
    chat_model = FakeListChatModel(
        responses=['{"incident_type": "ec2_high_cpu", "severity": "high"}', "Sustained high CPU."]
    )
    repo = InMemoryIncidentRepository()
    client = _build_test_client(gateway, chat_model, repo, DryRunAWSTools())

    incident_id = _create_high_cpu_incident(client, instance_arn)
    first = client.post(f"/remediation/{incident_id}/approve", json={"approved_by": "a@example.com"})
    assert first.status_code == 200

    second = client.post(f"/remediation/{incident_id}/approve", json={"approved_by": "b@example.com"})
    assert second.status_code == 409


def test_approve_incident_with_no_plan_returns_400() -> None:
    """HIGH_BILLING has no policy entries -- an incident classified that
    way never gets a proposed_remediation, so approving it should fail
    cleanly, not 500.
    """
    gateway = MockAWSGateway()
    chat_model = FakeListChatModel(responses=['{"incident_type": "high_billing", "severity": "critical"}'])
    repo = InMemoryIncidentRepository()
    client = _build_test_client(gateway, chat_model, repo, DryRunAWSTools())

    incident_id = _create_high_cpu_incident(client, "arn:aws:ec2:us-east-1:123456789012:instance/i-0no-plan")

    response = client.post(f"/remediation/{incident_id}/approve", json={"approved_by": "a@example.com"})

    assert response.status_code == 400


def test_approve_unknown_incident_returns_404() -> None:
    client = _build_test_client(MockAWSGateway(), FakeListChatModel(responses=["{}"]), InMemoryIncidentRepository(), DryRunAWSTools())

    response = client.post("/remediation/does-not-exist/approve", json={"approved_by": "a@example.com"})

    assert response.status_code == 404
