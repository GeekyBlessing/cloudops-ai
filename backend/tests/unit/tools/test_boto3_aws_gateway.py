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




def test_describe_instance_raises_key_error_when_response_has_no_instances() -> None:
    """Defensive check for a response shape describe_instances shouldn't
    actually produce via InstanceIds (real AWS -- and moto -- raise
    InvalidInstanceID.NotFound for a genuinely unknown id instead, see
    test_describe_instance_raises_for_unknown_id above), but the code
    guards against an empty Reservations list explicitly rather than
    assuming the SDK can never return one. Mocked directly since moto has
    no way to actually produce this response shape.
    """
    from unittest.mock import MagicMock

    gateway = Boto3AWSGateway(region=REGION)
    gateway._ec2 = MagicMock()
    gateway._ec2.describe_instances.return_value = {"Reservations": []}
    with pytest.raises(KeyError, match="i-empty-response"):
        gateway.describe_instance("i-empty-response")


def test_policy_marks_bucket_public_returns_false_when_no_policy_exists() -> None:
    """_policy_marks_bucket_public is never reached by the moto-based tests
    above (none of them put a bucket policy), so it's mocked directly here
    -- also sidesteps depending on moto's fidelity for
    get_bucket_policy_status's IsPublic computation.
    """
    from unittest.mock import MagicMock

    from botocore.exceptions import ClientError

    gateway = Boto3AWSGateway(region=REGION)
    gateway._s3 = MagicMock()
    gateway._s3.get_bucket_policy_status.side_effect = ClientError(
        {"Error": {"Code": "NoSuchBucketPolicy", "Message": "test"}}, "GetBucketPolicyStatus"
    )
    assert gateway._policy_marks_bucket_public("some-bucket") is False


def test_policy_marks_bucket_public_returns_true_when_policy_status_says_public() -> None:
    from unittest.mock import MagicMock

    gateway = Boto3AWSGateway(region=REGION)
    gateway._s3 = MagicMock()
    gateway._s3.get_bucket_policy_status.return_value = {"PolicyStatus": {"IsPublic": True}}
    assert gateway._policy_marks_bucket_public("some-bucket") is True


def test_policy_marks_bucket_public_reraises_unexpected_client_error() -> None:
    """Only the two documented not-public-policy error codes are treated as
    "not public" -- anything else (e.g. a permissions problem) must not be
    silently swallowed into a false "not public" result.
    """
    from unittest.mock import MagicMock

    from botocore.exceptions import ClientError

    gateway = Boto3AWSGateway(region=REGION)
    gateway._s3 = MagicMock()
    gateway._s3.get_bucket_policy_status.side_effect = ClientError(
        {"Error": {"Code": "AccessDenied", "Message": "test"}}, "GetBucketPolicyStatus"
    )
    with pytest.raises(ClientError):
        gateway._policy_marks_bucket_public("some-bucket")


def test_public_access_block_check_returns_false_when_not_configured() -> None:
    from unittest.mock import MagicMock

    from botocore.exceptions import ClientError

    gateway = Boto3AWSGateway(region=REGION)
    gateway._s3 = MagicMock()
    gateway._s3.get_public_access_block.side_effect = ClientError(
        {"Error": {"Code": "NoSuchPublicAccessBlockConfiguration", "Message": "test"}}, "GetPublicAccessBlock"
    )
    assert gateway._is_public_access_fully_blocked("some-bucket") is False


def test_public_access_block_check_reraises_unexpected_client_error() -> None:
    from unittest.mock import MagicMock

    from botocore.exceptions import ClientError

    gateway = Boto3AWSGateway(region=REGION)
    gateway._s3 = MagicMock()
    gateway._s3.get_public_access_block.side_effect = ClientError(
        {"Error": {"Code": "AccessDenied", "Message": "test"}}, "GetPublicAccessBlock"
    )
    with pytest.raises(ClientError):
        gateway._is_public_access_fully_blocked("some-bucket")


def test_lookup_cloudtrail_events_returns_json_safe_events() -> None:
    """lookup_cloudtrail_events has no test at all yet. Mocked directly --
    moto's CloudTrail support doesn't generate real lookup_events data
    (there's no real audit trail to look up in a fake account), so this is
    the only practical way to exercise the paginate-and-flatten logic.
    """
    from unittest.mock import MagicMock

    gateway = Boto3AWSGateway(region=REGION)
    now = datetime(2026, 7, 9, 12, 0, 0, tzinfo=timezone.utc)
    fake_paginator = MagicMock()
    fake_paginator.paginate.return_value = [{"Events": [{"EventId": "abc123", "EventTime": now}]}]
    gateway._cloudtrail = MagicMock()
    gateway._cloudtrail.get_paginator.return_value = fake_paginator

    result = gateway.lookup_cloudtrail_events(
        resource_arn="arn:aws:ec2:us-east-1:123456789012:instance/i-abc",
        start=now - timedelta(hours=1),
        end=now,
    )

    assert result == [{"EventId": "abc123", "EventTime": now.isoformat()}]
    gateway._cloudtrail.get_paginator.assert_called_once_with("lookup_events")


def test_lookup_cloudtrail_events_returns_empty_list_when_no_events() -> None:
    from unittest.mock import MagicMock

    gateway = Boto3AWSGateway(region=REGION)
    now = datetime.now(timezone.utc)
    fake_paginator = MagicMock()
    fake_paginator.paginate.return_value = [{}]
    gateway._cloudtrail = MagicMock()
    gateway._cloudtrail.get_paginator.return_value = fake_paginator

    result = gateway.lookup_cloudtrail_events(
        resource_arn="arn:aws:ec2:us-east-1:123456789012:instance/i-abc",
        start=now - timedelta(hours=1),
        end=now,
    )

    assert result == []


def test_get_guardduty_findings_returns_empty_list_when_detector_has_no_findings() -> None:
    """The skipped moto-based test above documents why this needs a mock:
    moto doesn't implement GuardDuty's ListFindings. Mocking the client
    directly closes the coverage gap moto currently blocks.
    """
    from unittest.mock import MagicMock

    gateway = Boto3AWSGateway(region=REGION)
    gateway._guardduty = MagicMock()
    gateway._guardduty.list_detectors.return_value = {"DetectorIds": ["detector-1"]}
    gateway._guardduty.list_findings.return_value = {"FindingIds": []}

    assert gateway.get_guardduty_findings() == []
    gateway._guardduty.get_findings.assert_not_called()


def test_get_guardduty_findings_returns_json_safe_findings() -> None:
    from unittest.mock import MagicMock

    gateway = Boto3AWSGateway(region=REGION)
    now = datetime(2026, 7, 9, 12, 0, 0, tzinfo=timezone.utc)
    gateway._guardduty = MagicMock()
    gateway._guardduty.list_detectors.return_value = {"DetectorIds": ["detector-1"]}
    gateway._guardduty.list_findings.return_value = {"FindingIds": ["finding-1"]}
    gateway._guardduty.get_findings.return_value = {
        "Findings": [{"Id": "finding-1", "CreatedAt": now, "Severity": Decimal("8.5")}]
    }

    result = gateway.get_guardduty_findings(severity_threshold=7.0)

    assert result == [{"Id": "finding-1", "CreatedAt": now.isoformat(), "Severity": 8.5}]
    gateway._guardduty.list_findings.assert_called_once_with(
        DetectorId="detector-1",
        FindingCriteria={"Criterion": {"severity": {"Gte": 7}}},
    )
