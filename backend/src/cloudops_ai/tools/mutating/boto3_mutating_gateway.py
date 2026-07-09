"""Real AWS mutating gateway, backed by boto3.

Implements IMutatingAWSTools (tools/interfaces.py) against actual AWS APIs:
EC2, Auto Scaling, S3, IAM, Lambda, and RDS. This is the ONLY adapter in the
codebase that ever makes a mutating boto3 call -- see IMutatingAWSTools's
docstring in tools/interfaces.py for why that boundary matters, and
get_mutating_aws_tools() in api/dependencies.py for how this class is gated
behind REMEDIATION_MODE=live plus a verified HMAC-signed approval (see
services/approval_service.py and RemediationPlan.can_execute_live() in
domain/models/remediation.py). No code path reaches this class without
passing through both of those gates first.

Every method here performs exactly one AWS mutation and nothing else -- no
retries, no rollback-on-partial-failure, no multi-step orchestration. That
kind of workflow logic belongs in the Remediation Executor
(agents/remediation_executor.py), which already has a FAILED status path
for exactly this case. Keeping this class "dumb" (one action name -> one
boto3 call, plus the minimum lookups AWS's API actually requires) keeps the
safety review surface small: auditing this file for "does it ever do more
than its method name implies" is a five-minute read, not an afternoon.
"""

from __future__ import annotations

import boto3

# Alias name this adapter assumes is used to route live traffic to a Lambda
# function version -- see rollback_function_version()'s docstring for why
# this assumption exists and what it would take to remove it.
_LIVE_ALIAS_NAME = "live"


class Boto3MutatingAWSGateway:
    """Satisfies IMutatingAWSTools using real boto3 clients.

    Accepts an optional pre-built `boto3.Session`, matching the pattern in
    Boto3AWSGateway (tools/readonly/boto3_aws_gateway.py) -- tests (moto)
    and production code (an assumed-role session for a tightly-scoped
    RemediationExecutorRole, deliberately distinct from the read-only
    MonitoringReadOnlyRole) control credentials explicitly, rather than
    this class reaching into ambient environment/instance-metadata
    credentials implicitly.
    """

    def __init__(self, region: str, session: boto3.Session | None = None) -> None:
        self._region = region
        session = session or boto3.Session(region_name=region)
        self._ec2 = session.client("ec2", region_name=region)
        self._autoscaling = session.client("autoscaling", region_name=region)
        self._s3 = session.client("s3", region_name=region)
        self._iam = session.client("iam", region_name=region)
        self._lambda = session.client("lambda", region_name=region)
        self._rds = session.client("rds", region_name=region)

    # ---------------- IMutatingAWSTools ----------------

    def reboot_instance(self, instance_id: str) -> None:
        self._ec2.reboot_instances(InstanceIds=[instance_id])

    def start_instance(self, instance_id: str) -> None:
        self._ec2.start_instances(InstanceIds=[instance_id])

    def scale_out(self, auto_scaling_group_name: str, increment: int) -> None:
        response = self._autoscaling.describe_auto_scaling_groups(
            AutoScalingGroupNames=[auto_scaling_group_name]
        )
        groups = response.get("AutoScalingGroups", [])
        if not groups:
            raise RuntimeError(f"No Auto Scaling Group found named {auto_scaling_group_name!r}")

        group = groups[0]
        # Capped at MaxSize -- scale_out is meant to add capacity within the
        # group's existing bounds, not silently override an operator-set
        # ceiling. If MaxSize itself needs raising, that's a deliberate,
        # separate change outside what a "scale out" remediation should do.
        new_desired = min(group["DesiredCapacity"] + increment, group["MaxSize"])
        self._autoscaling.set_desired_capacity(
            AutoScalingGroupName=auto_scaling_group_name,
            DesiredCapacity=new_desired,
            HonorCooldown=False,
        )

    def revoke_public_access(self, bucket_name: str) -> None:
        # A full public access block is the strongest, simplest fix -- it
        # overrides both ACL grants and bucket policy regardless of their
        # content, matching how Boto3AWSGateway.get_bucket_public_access
        # itself treats a full block as authoritative (see that method's
        # docstring in tools/readonly/boto3_aws_gateway.py). This does not
        # delete or modify the bucket policy/ACL themselves -- it just stops
        # them from taking effect, which is reversible and non-destructive.
        self._s3.put_public_access_block(
            Bucket=bucket_name,
            PublicAccessBlockConfiguration={
                "BlockPublicAcls": True,
                "IgnorePublicAcls": True,
                "BlockPublicPolicy": True,
                "RestrictPublicBuckets": True,
            },
        )

    def detach_overly_permissive_policy(self, role_name: str, policy_arn: str) -> None:
        self._iam.detach_role_policy(RoleName=role_name, PolicyArn=policy_arn)

    def rollback_function_version(self, function_name: str, target_version: str) -> None:
        """Repoint the function's `live` alias at `target_version`.

        Documented assumption: this adapter assumes traffic is routed
        through an alias named "live" (a common Lambda deployment pattern),
        rather than invoking $LATEST directly. If a deployment doesn't use
        that convention, this call will fail with an AWS ResourceNotFound
        error rather than silently doing nothing -- fail loud, not silent,
        consistent with this codebase's other safety defaults. Making the
        alias name configurable (e.g. per-function, via ResourceRef
        attributes) is a reasonable follow-up once a real deployment's
        alias conventions are known.
        """
        self._lambda.update_alias(
            FunctionName=function_name,
            Name=_LIVE_ALIAS_NAME,
            FunctionVersion=target_version,
        )

    def increase_storage_allocation(self, db_instance_identifier: str, new_allocated_storage_gb: int) -> None:
        self._rds.modify_db_instance(
            DBInstanceIdentifier=db_instance_identifier,
            AllocatedStorage=new_allocated_storage_gb,
            ApplyImmediately=True,
        )

    def reset_desired_capacity(self, auto_scaling_group_name: str, desired_capacity: int) -> None:
        self._autoscaling.set_desired_capacity(
            AutoScalingGroupName=auto_scaling_group_name,
            DesiredCapacity=desired_capacity,
            HonorCooldown=False,
        )
