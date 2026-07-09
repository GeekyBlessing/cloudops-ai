"""Dry-run mutating adapter -- the default binding for IMutatingAWSTools."""

from __future__ import annotations

import structlog

logger = structlog.get_logger(__name__)


class DryRunAWSTools:
    """Satisfies the IMutatingAWSTools protocol without mutating anything."""

    def __init__(self) -> None:
        self.actions_logged: list[dict[str, object]] = []

    def _log(self, action: str, **kwargs: object) -> None:
        entry: dict[str, object] = {"action": action, **kwargs}
        self.actions_logged.append(entry)
        logger.info("dry_run_remediation_action", **entry)

    def reboot_instance(self, instance_id: str) -> None:
        self._log("reboot_instance", instance_id=instance_id)

    def start_instance(self, instance_id: str) -> None:
        self._log("start_instance", instance_id=instance_id)

    def scale_out(self, auto_scaling_group_name: str, increment: int) -> None:
        self._log("scale_out", auto_scaling_group_name=auto_scaling_group_name, increment=increment)

    def revoke_public_access(self, bucket_name: str) -> None:
        self._log("revoke_public_access", bucket_name=bucket_name)

    def detach_overly_permissive_policy(self, role_name: str, policy_arn: str) -> None:
        self._log("detach_overly_permissive_policy", role_name=role_name, policy_arn=policy_arn)

    def rollback_function_version(self, function_name: str, target_version: str) -> None:
        self._log("rollback_function_version", function_name=function_name, target_version=target_version)

    def increase_storage_allocation(self, db_instance_identifier: str, new_allocated_storage_gb: int) -> None:
        self._log(
            "increase_storage_allocation",
            db_instance_identifier=db_instance_identifier,
            new_allocated_storage_gb=new_allocated_storage_gb,
        )

    def reset_desired_capacity(self, auto_scaling_group_name: str, desired_capacity: int) -> None:
        self._log(
            "reset_desired_capacity",
            auto_scaling_group_name=auto_scaling_group_name,
            desired_capacity=desired_capacity,
        )
