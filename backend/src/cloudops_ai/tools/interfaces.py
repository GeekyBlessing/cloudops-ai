"""Abstract AWS tool interfaces.

Agents never import boto3 directly -- they depend on these Protocols, and a
concrete adapter (real boto3, mock, or dry-run) is bound in at graph-build
time.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol

from cloudops_ai.domain.models.resource import ResourceRef


class IReadOnlyAWSTools(Protocol):
    """Read-only AWS operations available to every investigative agent."""

    def describe_instance(self, instance_id: str) -> ResourceRef: ...

    def get_metric_data(
        self,
        namespace: str,
        metric_name: str,
        dimensions: dict[str, str],
        start: datetime,
        end: datetime,
    ) -> list[dict[str, Any]]: ...

    def lookup_cloudtrail_events(self, resource_arn: str, start: datetime, end: datetime) -> list[dict[str, Any]]: ...

    def get_bucket_public_access(self, bucket_name: str) -> bool: ...

    def get_guardduty_findings(self, severity_threshold: float = 4.0) -> list[dict[str, Any]]: ...


class IMutatingAWSTools(Protocol):
    """Mutating AWS operations. Bound ONLY to the Remediation Executor."""

    def reboot_instance(self, instance_id: str) -> None: ...
    def start_instance(self, instance_id: str) -> None: ...
    def scale_out(self, auto_scaling_group_name: str, increment: int) -> None: ...
    def revoke_public_access(self, bucket_name: str) -> None: ...
    def detach_overly_permissive_policy(self, role_name: str, policy_arn: str) -> None: ...
    def rollback_function_version(self, function_name: str, target_version: str) -> None: ...
    def increase_storage_allocation(self, db_instance_identifier: str, new_allocated_storage_gb: int) -> None: ...
    def reset_desired_capacity(self, auto_scaling_group_name: str, desired_capacity: int) -> None: ...
