"""Unit tests for the in-memory mock AWS gateway."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from cloudops_ai.adapters.mock.mock_aws_gateway import MockAWSGateway
from cloudops_ai.domain.models.resource import ResourceRef


@pytest.fixture
def ec2_instance() -> ResourceRef:
    return ResourceRef(
        arn="arn:aws:ec2:us-east-1:123456789012:instance/i-0abcd1234",
        resource_type="AWS::EC2::Instance",
        region="us-east-1",
        account_id="123456789012",
        name="web-server-1",
        attributes={"state": "running", "instance_type": "t3.medium"},
    )


def test_describe_instance_returns_seeded_resource(ec2_instance: ResourceRef) -> None:
    gateway = MockAWSGateway(seed_resources=[ec2_instance])
    result = gateway.describe_instance("i-0abcd1234")
    assert result.arn == ec2_instance.arn
    assert result.attributes["state"] == "running"


def test_describe_instance_raises_for_unknown_id() -> None:
    gateway = MockAWSGateway()
    with pytest.raises(KeyError):
        gateway.describe_instance("i-doesnotexist")


def test_seeded_metric_data_round_trips(ec2_instance: ResourceRef) -> None:
    gateway = MockAWSGateway(seed_resources=[ec2_instance])
    now = datetime.now(timezone.utc)
    gateway.seed_metric_data(
        namespace="AWS/EC2",
        metric_name="CPUUtilization",
        dimensions={"InstanceId": "i-0abcd1234"},
        datapoints=[{"Timestamp": now.isoformat(), "Average": 95.4}],
    )
    result = gateway.get_metric_data(
        namespace="AWS/EC2",
        metric_name="CPUUtilization",
        dimensions={"InstanceId": "i-0abcd1234"},
        start=now,
        end=now,
    )
    assert result == [{"Timestamp": now.isoformat(), "Average": 95.4}]


def test_reboot_instance_is_recorded_in_mutation_log() -> None:
    gateway = MockAWSGateway()
    gateway.reboot_instance("i-0abcd1234")
    assert gateway.mutation_log == [{"action": "reboot_instance", "instance_id": "i-0abcd1234"}]


def test_revoke_public_access_updates_seeded_bucket_and_is_reflected_on_read() -> None:
    bucket = ResourceRef(
        arn="arn:aws:s3:::my-public-bucket",
        resource_type="AWS::S3::Bucket",
        region="us-east-1",
        account_id="123456789012",
        attributes={"is_public": True},
    )
    gateway = MockAWSGateway(seed_resources=[bucket])
    assert gateway.get_bucket_public_access("my-public-bucket") is True
    gateway.revoke_public_access("my-public-bucket")
    assert gateway.get_bucket_public_access("my-public-bucket") is False
    assert gateway.mutation_log[-1]["action"] == "revoke_public_access"


def test_seeded_cloudtrail_events_round_trip() -> None:
    gateway = MockAWSGateway()
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    arn = "arn:aws:lambda:us-east-1:123456789012:function:my-function"
    gateway.seed_cloudtrail_events(arn, [{"EventName": "UpdateFunctionCode", "EventTime": now.isoformat()}])

    result = gateway.lookup_cloudtrail_events(resource_arn=arn, start=now, end=now)

    assert result == [{"EventName": "UpdateFunctionCode", "EventTime": now.isoformat()}]


def test_lookup_cloudtrail_events_returns_empty_for_unseeded_arn() -> None:
    gateway = MockAWSGateway()
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    assert gateway.lookup_cloudtrail_events(resource_arn="arn:aws:s3:::unseeded", start=now, end=now) == []


def test_seeded_guardduty_findings_filtered_by_severity_threshold() -> None:
    gateway = MockAWSGateway()
    gateway.seed_guardduty_findings(
        [
            {"id": "finding-high", "severity": 8.0},
            {"id": "finding-low", "severity": 1.0},
        ]
    )

    result = gateway.get_guardduty_findings(severity_threshold=4.0)

    assert [finding["id"] for finding in result] == ["finding-high"]


def test_get_guardduty_findings_returns_empty_by_default() -> None:
    gateway = MockAWSGateway()
    assert gateway.get_guardduty_findings() == []
