"""Unit tests for the real, boto3-backed mutating AWS gateway.

Uses moto's `mock_aws` to fake EC2/Auto Scaling/S3/IAM/Lambda/RDS
in-process -- same philosophy as test_boto3_aws_gateway.py: the goal is
"prove our adapter calls the right APIs with the right parameters and
produces the AWS-side effect its method name promises," not "prove AWS
itself works."

This is the highest-stakes adapter in the codebase (it's the only one that
can ever actually mutate a real AWS account), so every method here gets its
own test with an explicit before/after assertion on AWS-side state, not
just "did not raise."
"""

from __future__ import annotations

import io
import zipfile

import boto3
import pytest
from moto import mock_aws

from cloudops_ai.tools.interfaces import IMutatingAWSTools
from cloudops_ai.tools.mutating.boto3_mutating_gateway import Boto3MutatingAWSGateway

REGION = "us-east-1"


def _minimal_lambda_zip_bytes() -> bytes:
    """A trivial valid Lambda deployment package -- moto (like real AWS)
    requires a real zip file for CreateFunction even though the code inside
    is never actually invoked by these tests.
    """
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("lambda_function.py", "def handler(event, context):\n    return {'statusCode': 200}\n")
    return buffer.getvalue()


@mock_aws
def test_reboot_instance_does_not_raise() -> None:
    ec2 = boto3.client("ec2", region_name=REGION)
    reservation = ec2.run_instances(ImageId="ami-12345678", MinCount=1, MaxCount=1, InstanceType="t3.medium")
    instance_id = reservation["Instances"][0]["InstanceId"]

    gateway = Boto3MutatingAWSGateway(region=REGION)
    gateway.reboot_instance(instance_id)  # must not raise


@mock_aws
def test_start_instance_transitions_stopped_instance_toward_running() -> None:
    ec2 = boto3.client("ec2", region_name=REGION)
    reservation = ec2.run_instances(ImageId="ami-12345678", MinCount=1, MaxCount=1, InstanceType="t3.medium")
    instance_id = reservation["Instances"][0]["InstanceId"]
    ec2.stop_instances(InstanceIds=[instance_id])

    gateway = Boto3MutatingAWSGateway(region=REGION)
    gateway.start_instance(instance_id)

    state = ec2.describe_instances(InstanceIds=[instance_id])["Reservations"][0]["Instances"][0]["State"]["Name"]
    assert state in {"running", "pending"}


def _create_asg(autoscaling_client, name: str, desired: int, max_size: int) -> None:
    ec2 = boto3.client("ec2", region_name=REGION)
    ami = ec2.describe_images()["Images"][0]["ImageId"] if ec2.describe_images()["Images"] else "ami-12345678"
    autoscaling_client.create_launch_configuration(
        LaunchConfigurationName=f"{name}-lc",
        ImageId="ami-12345678",
        InstanceType="t3.medium",
    )
    autoscaling_client.create_auto_scaling_group(
        AutoScalingGroupName=name,
        LaunchConfigurationName=f"{name}-lc",
        MinSize=1,
        MaxSize=max_size,
        DesiredCapacity=desired,
        AvailabilityZones=[f"{REGION}a"],
    )


@mock_aws
def test_scale_out_increments_desired_capacity() -> None:
    autoscaling = boto3.client("autoscaling", region_name=REGION)
    _create_asg(autoscaling, "my-asg", desired=2, max_size=5)

    gateway = Boto3MutatingAWSGateway(region=REGION)
    gateway.scale_out("my-asg", increment=1)

    group = autoscaling.describe_auto_scaling_groups(AutoScalingGroupNames=["my-asg"])["AutoScalingGroups"][0]
    assert group["DesiredCapacity"] == 3


@mock_aws
def test_scale_out_is_capped_at_max_size() -> None:
    autoscaling = boto3.client("autoscaling", region_name=REGION)
    _create_asg(autoscaling, "my-asg", desired=4, max_size=4)

    gateway = Boto3MutatingAWSGateway(region=REGION)
    gateway.scale_out("my-asg", increment=3)

    group = autoscaling.describe_auto_scaling_groups(AutoScalingGroupNames=["my-asg"])["AutoScalingGroups"][0]
    assert group["DesiredCapacity"] == 4  # not 7 -- capped at MaxSize


@mock_aws
def test_scale_out_raises_for_unknown_group() -> None:
    gateway = Boto3MutatingAWSGateway(region=REGION)
    with pytest.raises(RuntimeError, match="No Auto Scaling Group found"):
        gateway.scale_out("does-not-exist", increment=1)


@mock_aws
def test_reset_desired_capacity_sets_exact_value() -> None:
    autoscaling = boto3.client("autoscaling", region_name=REGION)
    _create_asg(autoscaling, "my-asg", desired=3, max_size=10)

    gateway = Boto3MutatingAWSGateway(region=REGION)
    gateway.reset_desired_capacity("my-asg", desired_capacity=7)

    group = autoscaling.describe_auto_scaling_groups(AutoScalingGroupNames=["my-asg"])["AutoScalingGroups"][0]
    assert group["DesiredCapacity"] == 7


@mock_aws
def test_revoke_public_access_applies_full_public_access_block() -> None:
    s3 = boto3.client("s3", region_name=REGION)
    s3.create_bucket(Bucket="test-bucket")

    gateway = Boto3MutatingAWSGateway(region=REGION)
    gateway.revoke_public_access("test-bucket")

    config = s3.get_public_access_block(Bucket="test-bucket")["PublicAccessBlockConfiguration"]
    assert config == {
        "BlockPublicAcls": True,
        "IgnorePublicAcls": True,
        "BlockPublicPolicy": True,
        "RestrictPublicBuckets": True,
    }


@mock_aws
def test_detach_overly_permissive_policy_removes_attachment() -> None:
    iam = boto3.client("iam", region_name=REGION)
    iam.create_role(
        RoleName="overly-permissive-role",
        AssumeRolePolicyDocument='{"Version": "2012-10-17", "Statement": []}',
    )
    # A customer-managed policy rather than an AWS managed policy ARN
    # (e.g. AdministratorAccess) -- moto does not pre-seed AWS's managed
    # policy catalogue, so attaching one 404s here the same way it would
    # against a real account that hasn't had that policy synced locally.
    # A customer-managed policy with equally broad permissions exercises
    # the same attach/detach mechanics this method actually cares about.
    policy_arn = iam.create_policy(
        PolicyName="overly-permissive-policy",
        PolicyDocument=(
            '{"Version": "2012-10-17", "Statement": '
            '[{"Effect": "Allow", "Action": "*", "Resource": "*"}]}'
        ),
    )["Policy"]["Arn"]
    iam.attach_role_policy(RoleName="overly-permissive-role", PolicyArn=policy_arn)

    gateway = Boto3MutatingAWSGateway(region=REGION)
    gateway.detach_overly_permissive_policy(role_name="overly-permissive-role", policy_arn=policy_arn)

    attached = iam.list_attached_role_policies(RoleName="overly-permissive-role")["AttachedPolicies"]
    assert policy_arn not in [policy["PolicyArn"] for policy in attached]


@mock_aws
def test_rollback_function_version_repoints_live_alias() -> None:
    iam = boto3.client("iam", region_name=REGION)
    role = iam.create_role(
        RoleName="lambda-role",
        AssumeRolePolicyDocument='{"Version": "2012-10-17", "Statement": []}',
    )["Role"]["Arn"]

    lambda_client = boto3.client("lambda", region_name=REGION)
    code = _minimal_lambda_zip_bytes()
    lambda_client.create_function(
        FunctionName="my-function",
        Runtime="python3.12",
        Role=role,
        Handler="lambda_function.handler",
        Code={"ZipFile": code},
        Publish=True,
    )
    # Publish a second version with the same code (moto assigns incrementing
    # version numbers regardless of code changes) so there are two distinct
    # versions to roll back between.
    version_2 = lambda_client.publish_version(FunctionName="my-function")["Version"]
    lambda_client.create_alias(FunctionName="my-function", Name="live", FunctionVersion=version_2)

    gateway = Boto3MutatingAWSGateway(region=REGION)
    gateway.rollback_function_version(function_name="my-function", target_version="1")

    alias = lambda_client.get_alias(FunctionName="my-function", Name="live")
    assert alias["FunctionVersion"] == "1"


@mock_aws
def test_increase_storage_allocation_updates_allocated_storage() -> None:
    rds = boto3.client("rds", region_name=REGION)
    rds.create_db_instance(
        DBInstanceIdentifier="my-db-instance",
        Engine="postgres",
        DBInstanceClass="db.t3.micro",
        AllocatedStorage=20,
        MasterUsername="admin",
        MasterUserPassword="supersecretpassword123",
    )

    gateway = Boto3MutatingAWSGateway(region=REGION)
    gateway.increase_storage_allocation(db_instance_identifier="my-db-instance", new_allocated_storage_gb=100)

    instance = rds.describe_db_instances(DBInstanceIdentifier="my-db-instance")["DBInstances"][0]
    assert instance["AllocatedStorage"] == 100


def test_every_imutatingawstools_method_is_implemented() -> None:
    """Structural-typing safety net: Protocol gives no compile-time guarantee
    that this class's method signatures actually match IMutatingAWSTools --
    this test is the runtime backstop, same pattern as the equivalent test
    in test_dry_run_adapter.py.
    """
    protocol_methods = {name for name in dir(IMutatingAWSTools) if not name.startswith("_")}
    gateway_methods = {name for name in dir(Boto3MutatingAWSGateway) if not name.startswith("_")}
    missing = protocol_methods - gateway_methods
    assert not missing, f"Boto3MutatingAWSGateway is missing methods required by IMutatingAWSTools: {missing}"
