"""Unit tests for the Infrastructure Agent node."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from cloudops_ai.adapters.mock.mock_aws_gateway import MockAWSGateway
from cloudops_ai.agents.infrastructure_agent import make_infrastructure_node
from cloudops_ai.domain.enums import IncidentType, TriggerSource
from cloudops_ai.domain.models.incident import IncidentState
from cloudops_ai.domain.models.resource import ResourceRef


def _incident(incident_type: IncidentType, resources: list[ResourceRef]) -> IncidentState:
    return IncidentState(
        incident_id="incident-1",
        trigger_source=TriggerSource.CLOUDWATCH_ALARM,
        affected_resources=resources,
        incident_type=incident_type,
    )


def test_ec2_down_confirms_stopped_instance() -> None:
    instance = ResourceRef(
        arn="arn:aws:ec2:us-east-1:123456789012:instance/i-0abcd1234",
        resource_type="AWS::EC2::Instance",
        region="us-east-1",
        account_id="123456789012",
        attributes={"state": "stopped"},
    )
    gateway = MockAWSGateway(seed_resources=[instance])
    incident = _incident(IncidentType.EC2_DOWN, [instance])

    node = make_infrastructure_node(gateway)
    result = node({"incident": incident})
    updated = result["incident"]

    assert updated.evidence[0].data["state"] == "stopped"
    assert "confirms" in updated.agent_trace[0].reasoning


def test_ec2_down_does_not_confirm_running_instance() -> None:
    instance = ResourceRef(
        arn="arn:aws:ec2:us-east-1:123456789012:instance/i-0abcd1234",
        resource_type="AWS::EC2::Instance",
        region="us-east-1",
        account_id="123456789012",
        attributes={"state": "running"},
    )
    gateway = MockAWSGateway(seed_resources=[instance])
    incident = _incident(IncidentType.EC2_DOWN, [instance])

    node = make_infrastructure_node(gateway)
    result = node({"incident": incident})

    assert "does not confirm" in result["incident"].agent_trace[0].reasoning


def test_rds_storage_full_flags_low_free_storage() -> None:
    db = ResourceRef(
        arn="arn:aws:rds:us-east-1:123456789012:db:my-db-instance",
        resource_type="AWS::RDS::DBInstance",
        region="us-east-1",
        account_id="123456789012",
    )
    gateway = MockAWSGateway(seed_resources=[db])
    now = datetime.now(timezone.utc)
    gateway.seed_metric_data(
        namespace="AWS/RDS",
        metric_name="FreeStorageSpace",
        dimensions={"DBInstanceIdentifier": "my-db-instance"},
        datapoints=[{"Timestamp": now.isoformat(), "Average": 500_000_000.0}],  # 0.5 GB, below threshold
    )
    incident = _incident(IncidentType.RDS_STORAGE_FULL, [db])

    node = make_infrastructure_node(gateway)
    result = node({"incident": incident})
    updated = result["incident"]

    assert updated.evidence[0].data["mean_free_bytes"] == pytest.approx(500_000_000.0)
    assert "Flagging as low storage" in updated.agent_trace[0].reasoning


def test_no_op_for_unrelated_incident_type() -> None:
    gateway = MockAWSGateway()
    instance = ResourceRef(
        arn="arn:aws:ec2:us-east-1:123456789012:instance/i-0abcd1234",
        resource_type="AWS::EC2::Instance",
        region="us-east-1",
        account_id="123456789012",
    )
    incident = _incident(IncidentType.EC2_HIGH_CPU, [instance])

    node = make_infrastructure_node(gateway)
    result = node({"incident": incident})

    assert result["incident"].evidence == []
    assert "no investigation logic" in result["incident"].agent_trace[0].reasoning


def test_no_affected_resource_is_handled_gracefully() -> None:
    gateway = MockAWSGateway()
    incident = _incident(IncidentType.EC2_DOWN, [])

    node = make_infrastructure_node(gateway)
    result = node({"incident": incident})

    assert result["incident"].evidence == []
    assert len(result["incident"].agent_trace) == 1
