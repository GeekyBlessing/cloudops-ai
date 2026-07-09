"""Unit tests for the real, boto3-backed AWS gateway.

Uses moto's `mock_aws` to fake EC2/CloudWatch/S3/GuardDuty in-process. The
goal here is narrower than "prove AWS behaves correctly" (that's AWS's job,
and moto's) -- it's "prove our adapter calls the right APIs, handles the
not-found cases, and always returns JSON-safe data," which is the actual
contract IReadOnlyAWSTools promises the rest of the system.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import boto3
import pytest
from moto import mock_aws

from cloudops_ai.tools.readonly.boto3_aws_gateway import Boto3AWSGateway, _json_safe

REGION = "us-east-1"


def test_json_safe_converts_datetime_and_decimal_recursively() -> None:
    now = datetime(2026, 7, 9, 12, 0, 0, tzinfo=timezone.utc)
    raw = {"Timestamp": now, "Average": Decimal("95.5"), "Nested": [{"When": now, "Count": Decimal("3")}]}

    safe = _json_safe(raw)

    assert safe["Timestamp"] == now.isoformat()
    assert safe["Average"] == 95.5
    assert isinstance(safe["Average"], float)
    assert safe["Nested"][0]["When"] == now.isoformat()
    json.dumps(safe)  # must not raise


@mock_aws
def test_describe_instance_returns_resource_ref_for_real_instance() -> None:
    ec2 = boto3.client("ec2", region_name=REGION)
    reservation = ec2.run_instances(ImageId="ami-12345678", MinCount=1, MaxCount=1, InstanceType="t3.medium")
    instance_id = reservation["Instances"][0]["InstanceId"]
    ec2.create_tags(Resources=[instance_id], Tags=[{"Key": "Name", "Value": "web-server-1"}])

    gateway = Boto3AWSGateway(region=REGION)
    resource = gateway.describe_instance(instance_id)

    assert resource.arn.endswith(f"instance/{instance_id}")
    assert resource.resource_type == "AWS::EC2::Instance"
    assert resource.name == "web-server-1"
    assert resource.attributes["instance_type"] == "t3.medium"


@mock_aws
def test_describe_instance_raises_for_unknown_id() -> None:
    gateway = Boto3AWSGateway(region=REGION)
    with pytest.raises(Exception):  # noqa: B017 -- boto3 raises its own ClientError subclass here
        gateway.describe_instance("i-doesnotexist")


@mock_aws
def test_get_metric_data_returns_json_safe_datapoints() -> None:
    cloudwatch = boto3.client("cloudwatch", region_name=REGION)
    now = datetime.now(timezone.utc)
    cloudwatch.put_metric_data(
        Namespace="AWS/EC2",
        MetricData=[
            {
                "MetricName": "CPUUtilization",
                "Dimensions": [{"Name": "InstanceId", "Value": "i-0abcd1234"}],
                "Timestamp": now,
                "Value": 95.0,
                "Unit": "Percent",
            }
        ],
    )

    gateway = Boto3AWSGateway(region=REGION)
    result = gateway.get_metric_data(
        namespace="AWS/EC2",
        metric_name="CPUUtilization",
        dimensions={"InstanceId": "i-0abcd1234"},
        start=now - timedelta(minutes=10),
        end=now + timedelta(minutes=10),
    )

    assert isinstance(result, list)
    json.dumps(result)  # every datapoint must already be JSON-serializable


@mock_aws
def test_new_bucket_is_not_public_by_default() -> None:
    s3 = boto3.client("s3", region_name=REGION)
    s3.create_bucket(Bucket="test-bucket")

    gateway = Boto3AWSGateway(region=REGION)
    assert gateway.get_bucket_public_access("test-bucket") is False


@mock_aws
def test_bucket_with_public_acl_grant_is_detected_as_public() -> None:
    s3 = boto3.client("s3", region_name=REGION)
    s3.create_bucket(Bucket="test-bucket")

    acl = s3.get_bucket_acl(Bucket="test-bucket")
    acl["Grants"].append(
        {
            "Grantee": {"Type": "Group", "URI": "http://acs.amazonaws.com/groups/global/AllUsers"},
            "Permission": "READ",
        }
    )
    s3.put_bucket_acl(Bucket="test-bucket", AccessControlPolicy={"Grants": acl["Grants"], "Owner": acl["Owner"]})

    gateway = Boto3AWSGateway(region=REGION)
    assert gateway.get_bucket_public_access("test-bucket") is True


@mock_aws
def test_public_access_block_overrides_public_acl_grant() -> None:
    """A full public-access-block wins over a public ACL grant -- this is
    the exact scenario the layered check in get_bucket_public_access exists
    for: don't flag a bucket as publicly exposed if AWS itself is already
    blocking that exposure account-wide.
    """
    s3 = boto3.client("s3", region_name=REGION)
    s3.create_bucket(Bucket="test-bucket")

    acl = s3.get_bucket_acl(Bucket="test-bucket")
    acl["Grants"].append(
        {
            "Grantee": {"Type": "Group", "URI": "http://acs.amazonaws.com/groups/global/AllUsers"},
            "Permission": "READ",
        }
    )
    s3.put_bucket_acl(Bucket="test-bucket", AccessControlPolicy={"Grants": acl["Grants"], "Owner": acl["Owner"]})
    s3.put_public_access_block(
        Bucket="test-bucket",
        PublicAccessBlockConfiguration={
            "BlockPublicAcls": True,
            "IgnorePublicAcls": True,
            "BlockPublicPolicy": True,
            "RestrictPublicBuckets": True,
        },
    )

    gateway = Boto3AWSGateway(region=REGION)
    assert gateway.get_bucket_public_access("test-bucket") is False


@mock_aws
def test_get_guardduty_findings_returns_empty_list_when_no_detector() -> None:
    gateway = Boto3AWSGateway(region=REGION)
    assert gateway.get_guardduty_findings() == []


@pytest.mark.skip(
    reason="moto does not yet implement GuardDuty's ListFindings API (returns HTTP 404 "
    "'Not yet implemented'). The no-detector path above covers the early-return branch; "
    "this branch needs either a moto version update or a LocalStack-backed integration "
    "test to exercise for real. Tracked as a follow-up, not silently dropped."
)
@mock_aws
def test_get_guardduty_findings_returns_empty_list_when_detector_has_no_findings() -> None:
    guardduty = boto3.client("guardduty", region_name=REGION)
    guardduty.create_detector(Enable=True)

    gateway = Boto3AWSGateway(region=REGION)
    assert gateway.get_guardduty_findings() == []
