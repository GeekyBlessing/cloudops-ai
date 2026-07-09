"""Unit tests for the Security Agent node."""

from __future__ import annotations

from cloudops_ai.adapters.mock.mock_aws_gateway import MockAWSGateway
from cloudops_ai.agents.security_agent import make_security_node
from cloudops_ai.domain.enums import IncidentType, TriggerSource
from cloudops_ai.domain.models.incident import IncidentState
from cloudops_ai.domain.models.resource import ResourceRef


def _incident(incident_type: IncidentType, resources: list[ResourceRef]) -> IncidentState:
    incident = IncidentState(
        incident_id="incident-1",
        trigger_source=TriggerSource.CLOUDWATCH_ALARM,
        affected_resources=resources,
        incident_type=incident_type,
    )
    return incident


def test_public_s3_bucket_detects_public_access() -> None:
    bucket = ResourceRef(
        arn="arn:aws:s3:::my-public-bucket",
        resource_type="AWS::S3::Bucket",
        region="us-east-1",
        account_id="123456789012",
        attributes={"is_public": True},
    )
    gateway = MockAWSGateway(seed_resources=[bucket])
    incident = _incident(IncidentType.PUBLIC_S3_BUCKET, [bucket])

    node = make_security_node(gateway)
    result = node({"incident": incident})
    updated = result["incident"]

    assert len(updated.evidence) == 1
    assert updated.evidence[0].data["is_public"] is True
    assert "PUBLIC" in updated.evidence[0].summary
    assert "requires remediation" in updated.agent_trace[0].reasoning


def test_public_s3_bucket_detects_non_public_bucket() -> None:
    bucket = ResourceRef(
        arn="arn:aws:s3:::my-private-bucket",
        resource_type="AWS::S3::Bucket",
        region="us-east-1",
        account_id="123456789012",
        attributes={"is_public": False},
    )
    gateway = MockAWSGateway(seed_resources=[bucket])
    incident = _incident(IncidentType.PUBLIC_S3_BUCKET, [bucket])

    node = make_security_node(gateway)
    result = node({"incident": incident})

    assert result["incident"].evidence[0].data["is_public"] is False


def test_iam_misconfiguration_reports_guardduty_findings() -> None:
    gateway = MockAWSGateway()
    gateway.seed_guardduty_findings(
        [
            {"id": "finding-1", "severity": 8.0, "type": "PrivilegeEscalation:IAMUser/AdministrativePermissions"},
            {"id": "finding-2", "severity": 2.0, "type": "Recon:IAMUser/TorIPCaller"},
        ]
    )
    role = ResourceRef(
        arn="arn:aws:iam::123456789012:role/overly-permissive-role",
        resource_type="AWS::IAM::Role",
        region="us-east-1",
        account_id="123456789012",
    )
    incident = _incident(IncidentType.IAM_MISCONFIGURATION, [role])

    node = make_security_node(gateway)
    result = node({"incident": incident})
    updated = result["incident"]

    # Only the severity-8.0 finding clears the default 4.0 threshold.
    assert len(updated.evidence[0].data["findings"]) == 1
    assert updated.evidence[0].data["findings"][0]["id"] == "finding-1"


def test_no_op_for_unrelated_incident_type() -> None:
    gateway = MockAWSGateway()
    incident = _incident(IncidentType.EC2_HIGH_CPU, [])

    node = make_security_node(gateway)
    result = node({"incident": incident})

    assert result["incident"].evidence == []
    assert "no investigation logic" in result["incident"].agent_trace[0].reasoning


def test_public_s3_bucket_with_no_affected_resource_is_handled_gracefully() -> None:
    gateway = MockAWSGateway()
    incident = _incident(IncidentType.PUBLIC_S3_BUCKET, [])

    node = make_security_node(gateway)
    result = node({"incident": incident})

    assert result["incident"].evidence == []
    assert len(result["incident"].agent_trace) == 1
