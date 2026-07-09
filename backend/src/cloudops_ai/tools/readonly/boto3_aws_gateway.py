"""Real AWS read-only gateway, backed by boto3.

Implements IReadOnlyAWSTools (tools/interfaces.py) against actual AWS APIs:
EC2, CloudWatch, CloudTrail, S3, and GuardDuty. This is what
MonitoringReadOnlyRole (see /docs/ARCHITECTURE.md section 6) actually calls
in a deployed environment -- every method here is read-only by construction
(no put_/create_/delete_/modify_ boto3 calls anywhere in this file), which
is the whole point of it being safe to hand to every investigative agent.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

import boto3
from botocore.exceptions import ClientError

from cloudops_ai.domain.models.resource import ResourceRef

_PUBLIC_GROUP_URIS = {
    "http://acs.amazonaws.com/groups/global/AllUsers",
    "http://acs.amazonaws.com/groups/global/AuthenticatedUsers",
}


def _json_safe(value: Any) -> Any:
    """Recursively convert datetimes/Decimals in a boto3 response into
    JSON-serializable equivalents.

    boto3 response dicts routinely contain `datetime` objects (and,
    depending on the service, `Decimal`), neither of which pydantic's `Any`
    fields serialize automatically in every code path. Evidence.data is
    typed `dict[str, Any]` specifically so any AWS response can be dropped
    in directly -- this function is what keeps that promise honest, by
    guaranteeing the result is always plain JSON-safe Python before it ever
    reaches an Evidence object.
    """
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value


class Boto3AWSGateway:
    """Satisfies IReadOnlyAWSTools using real boto3 clients.

    Accepts an optional pre-built `boto3.Session` so tests (via moto) and
    production code (an assumed-role session for MonitoringReadOnlyRole)
    control credentials explicitly, rather than this class reaching into
    ambient environment/instance-metadata credentials implicitly.
    """

    def __init__(self, region: str, session: boto3.Session | None = None) -> None:
        self._region = region
        session = session or boto3.Session(region_name=region)
        self._ec2 = session.client("ec2", region_name=region)
        self._cloudwatch = session.client("cloudwatch", region_name=region)
        self._cloudtrail = session.client("cloudtrail", region_name=region)
        self._s3 = session.client("s3", region_name=region)
        self._guardduty = session.client("guardduty", region_name=region)
        self._sts = session.client("sts", region_name=region)
        self.__account_id: str | None = None

    def _account_id(self) -> str:
        """Cached per adapter instance -- the account ID never changes for
        the lifetime of one set of credentials, so there is no reason to
        pay for an STS call on every ARN we construct.
        """
        if self.__account_id is None:
            self.__account_id = self._sts.get_caller_identity()["Account"]
        return self.__account_id

    # ---------------- IReadOnlyAWSTools ----------------

    def describe_instance(self, instance_id: str) -> ResourceRef:
        response = self._ec2.describe_instances(InstanceIds=[instance_id])
        reservations = response.get("Reservations", [])
        if not reservations or not reservations[0].get("Instances"):
            raise KeyError(f"No EC2 instance found for id {instance_id!r}")

        instance = reservations[0]["Instances"][0]
        tags = {tag["Key"]: tag["Value"] for tag in instance.get("Tags", [])}
        account_id = self._account_id()

        return ResourceRef(
            arn=f"arn:aws:ec2:{self._region}:{account_id}:instance/{instance_id}",
            resource_type="AWS::EC2::Instance",
            region=self._region,
            account_id=account_id,
            name=tags.get("Name"),
            tags=tags,
            attributes=_json_safe(
                {
                    "state": instance.get("State", {}).get("Name"),
                    "instance_type": instance.get("InstanceType"),
                    "launch_time": instance.get("LaunchTime"),
                    "private_ip": instance.get("PrivateIpAddress"),
                    "public_ip": instance.get("PublicIpAddress"),
                }
            ),
        )

    def get_metric_data(
        self,
        namespace: str,
        metric_name: str,
        dimensions: dict[str, str],
        start: datetime,
        end: datetime,
    ) -> list[dict[str, Any]]:
        response = self._cloudwatch.get_metric_statistics(
            Namespace=namespace,
            MetricName=metric_name,
            Dimensions=[{"Name": key, "Value": value} for key, value in dimensions.items()],
            StartTime=start,
            EndTime=end,
            Period=300,
            Statistics=["Average", "Maximum"],
        )
        datapoints = sorted(response.get("Datapoints", []), key=lambda dp: dp["Timestamp"])
        return [_json_safe(dp) for dp in datapoints]

    def lookup_cloudtrail_events(self, resource_arn: str, start: datetime, end: datetime) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        paginator = self._cloudtrail.get_paginator("lookup_events")
        for page in paginator.paginate(
            LookupAttributes=[{"AttributeKey": "ResourceName", "AttributeValue": resource_arn}],
            StartTime=start,
            EndTime=end,
        ):
            events.extend(page.get("Events", []))
        return [_json_safe(event) for event in events]

    def get_bucket_public_access(self, bucket_name: str) -> bool:
        """Mirrors how AWS Config's own public-bucket rule reasons about
        this: a public access block that fully blocks everything wins
        regardless of what the policy or ACL say; short of that, a policy
        AWS itself evaluates as public wins; short of that, fall back to
        checking the ACL for a grant to the AllUsers/AuthenticatedUsers
        groups. This is deliberately AWS's own evaluation logic
        (`get_bucket_policy_status`), not a hand-rolled policy parser --
        reinventing IAM policy evaluation is a well-known way to get
        security tooling subtly wrong.
        """
        if self._is_public_access_fully_blocked(bucket_name):
            return False
        if self._policy_marks_bucket_public(bucket_name):
            return True
        return self._acl_grants_public_access(bucket_name)

    def _is_public_access_fully_blocked(self, bucket_name: str) -> bool:
        try:
            response = self._s3.get_public_access_block(Bucket=bucket_name)
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "NoSuchPublicAccessBlockConfiguration":
                return False
            raise
        config = response["PublicAccessBlockConfiguration"]
        return all(
            config.get(key, False)
            for key in ("BlockPublicAcls", "IgnorePublicAcls", "BlockPublicPolicy", "RestrictPublicBuckets")
        )

    def _policy_marks_bucket_public(self, bucket_name: str) -> bool:
        try:
            response = self._s3.get_bucket_policy_status(Bucket=bucket_name)
        except ClientError as exc:
            if exc.response["Error"]["Code"] in ("NoSuchBucketPolicy", "NoSuchBucket"):
                return False
            raise
        return bool(response.get("PolicyStatus", {}).get("IsPublic", False))

    def _acl_grants_public_access(self, bucket_name: str) -> bool:
        response = self._s3.get_bucket_acl(Bucket=bucket_name)
        return any(
            grant.get("Grantee", {}).get("URI") in _PUBLIC_GROUP_URIS for grant in response.get("Grants", [])
        )

    def get_guardduty_findings(self, severity_threshold: float = 4.0) -> list[dict[str, Any]]:
        detector_ids = self._guardduty.list_detectors().get("DetectorIds", [])
        if not detector_ids:
            return []

        detector_id = detector_ids[0]

        finding_ids = self._guardduty.list_findings(
            DetectorId=detector_id,
            FindingCriteria={"Criterion": {"severity": {"Gte": int(severity_threshold)}}},
        ).get("FindingIds", [])
        if not finding_ids:
            return []

        findings = self._guardduty.get_findings(DetectorId=detector_id, FindingIds=finding_ids).get("Findings", [])
        return [_json_safe(finding) for finding in findings]
