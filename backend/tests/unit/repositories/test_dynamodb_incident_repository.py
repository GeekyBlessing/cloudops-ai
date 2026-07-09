"""Unit tests for the DynamoDB-backed incident repository.

Uses moto's `mock_aws` to fake the DynamoDB API in-process -- no real AWS
account, no Docker, no network call. This is a deliberately different test
strategy from "spin up DynamoDB Local": moto is for fast, isolated unit
tests (this file, and CI); docker-compose + DynamoDB Local
(see /docker-compose.yml) is for interactive local development against
something closer to the real service.
"""

from __future__ import annotations

from datetime import datetime, timezone

import boto3
import pytest
from moto import mock_aws

from cloudops_ai.domain.enums import AgentName, IncidentType, RemediationStatus, Severity, TriggerSource
from cloudops_ai.domain.models.evidence import AgentStep, Evidence
from cloudops_ai.domain.models.incident import IncidentState
from cloudops_ai.repositories.dynamodb_incident_repository import DynamoDBIncidentRepository

TABLE_NAME = "test-incidents"
REGION = "us-east-1"


def _create_table() -> None:
    client = boto3.client("dynamodb", region_name=REGION)
    client.create_table(
        TableName=TABLE_NAME,
        KeySchema=[{"AttributeName": "incident_id", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "incident_id", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )


@pytest.fixture
def repository():
    with mock_aws():
        _create_table()
        yield DynamoDBIncidentRepository(table_name=TABLE_NAME, region=REGION)


def test_save_and_get_round_trips_full_incident(repository: DynamoDBIncidentRepository) -> None:
    incident = IncidentState(
        incident_id="incident-1",
        trigger_source=TriggerSource.CLOUDWATCH_ALARM,
        incident_type=IncidentType.EC2_HIGH_CPU,
        severity=Severity.HIGH,
    )

    repository.save(incident)
    fetched = repository.get("incident-1")

    assert fetched is not None
    assert fetched.incident_id == "incident-1"
    assert fetched.incident_type == IncidentType.EC2_HIGH_CPU
    assert fetched.severity == Severity.HIGH


def test_get_returns_none_for_missing_incident(repository: DynamoDBIncidentRepository) -> None:
    assert repository.get("does-not-exist") is None


def test_list_all_returns_most_recent_first(repository: DynamoDBIncidentRepository) -> None:
    older = IncidentState(
        incident_id="incident-old",
        trigger_source=TriggerSource.MANUAL,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    newer = IncidentState(
        incident_id="incident-new",
        trigger_source=TriggerSource.MANUAL,
        created_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
        updated_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
    )

    repository.save(older)
    repository.save(newer)

    results = repository.list_all()

    assert [incident.incident_id for incident in results] == ["incident-new", "incident-old"]


def test_save_preserves_evidence_and_agent_trace(repository: DynamoDBIncidentRepository) -> None:
    """Guards against the one-attribute-per-field trap: everything nested
    under the incident (evidence, agent_trace) must survive a save/get
    round trip via the JSON document attribute, not just the top-level
    scalar fields used for querying.
    """
    incident = IncidentState(incident_id="incident-2", trigger_source=TriggerSource.CLOUDWATCH_ALARM)
    incident.add_evidence(
        Evidence(evidence_id="ev-1", agent=AgentName.MONITORING, source="cloudwatch", summary="CPU spike")
    )
    incident.add_agent_step(
        AgentStep(step_id="step-1", agent=AgentName.MONITORING, reasoning="Investigated CPU metrics")
    )

    repository.save(incident)
    fetched = repository.get("incident-2")

    assert fetched is not None
    assert len(fetched.evidence) == 1
    assert fetched.evidence[0].evidence_id == "ev-1"
    assert len(fetched.agent_trace) == 1
    assert fetched.agent_trace[0].reasoning == "Investigated CPU metrics"


def test_severity_none_is_stored_and_read_back_as_none(repository: DynamoDBIncidentRepository) -> None:
    """severity defaults to None until the Coordinator classifies the
    incident -- the "unset" sentinel written to the top-level attribute
    must not leak into the document's own severity field on read.
    """
    incident = IncidentState(incident_id="incident-3", trigger_source=TriggerSource.MANUAL)
    assert incident.severity is None

    repository.save(incident)
    fetched = repository.get("incident-3")

    assert fetched is not None
    assert fetched.severity is None
    assert fetched.remediation_status == RemediationStatus.NOT_STARTED
