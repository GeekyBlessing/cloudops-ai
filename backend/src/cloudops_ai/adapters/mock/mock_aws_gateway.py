"""In-memory mock AWS gateway.

Implements both IReadOnlyAWSTools and IMutatingAWSTools using an in-memory
dict of fixture resources instead of real boto3 calls. This is the adapter
bound in for local development (docker-compose, no AWS credentials needed)
and for every unit/agent test that touches "AWS" -- see
/docs/ARCHITECTURE.md section 3 for where this fits versus the real and
dry-run adapters.

Mutating methods here DO mutate this object's own in-memory state (so a
test can do "call reboot_instance, then assert the recorded mutation"), but
never touch a real AWS account. This is different from DryRunAWSTools
(tools/dry_run/dry_run_adapter.py), which only logs an intended action --
this class exists so *agent logic* can be tested against something that
behaves like AWS, while DryRunAWSTools exists so the *remediation executor's
safety gating* can be tested in isolation.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from cloudops_ai.domain.models.resource import ResourceRef


class MockAWSGateway:
    """A single class implementing both tool Protocols against in-memory
    fixture data.

    Structural typing (Protocol) means this class needs no inheritance from
    IReadOnlyAWSTools/IMutatingAWSTools -- it satisfies both simply by
    having matching method signatures. `mypy --strict` will still catch a
    signature drift if this class is passed somewhere an IReadOnlyAWSTools
    or IMutatingAWSTools is expected.
    """

    def __init__(self, seed_resources: list[ResourceRef] | None = None) -> None:
        """`seed_resources` lets each test set up exactly the fixture data
        it needs (e.g. one EC2 instance already reporting 95% CPU) instead
        of every test sharing one global fixture that's hard to reason
        about in isolation.
        """
        self._resources: dict[str, ResourceRef] = {r.arn: r for r in (seed_resources or [])}
        self._metric_data: dict[str, list[dict[str, Any]]] = {}
        # Keyed by resource_arn -- lookup_cloudtrail_events returns whatever
        # was seeded for that exact ARN, same "explicit fixture per test"
        # philosophy as _metric_data.
        self._cloudtrail_events: dict[str, list[dict[str, Any]]] = {}
        # Not keyed by anything -- GuardDuty findings aren't scoped to a
        # single resource ARN in the real API either (ListFindings returns
        # account-wide findings you then filter/correlate yourself), so one
        # flat list mirrors that shape.
        self._guardduty_findings: list[dict[str, Any]] = []
        # Every mutating call appends here, in order -- tests assert
        # against this list rather than re-implementing AWS state machines.
        self.mutation_log: list[dict[str, Any]] = []

    # ---------------- IReadOnlyAWSTools ----------------

    def describe_instance(self, instance_id: str) -> ResourceRef:
        for resource in self._resources.values():
            if resource.arn.endswith(f"instance/{instance_id}"):
                return resource
        raise KeyError(f"No mock EC2 instance registered for id {instance_id!r}")

    def get_metric_data(
        self,
        namespace: str,
        metric_name: str,
        dimensions: dict[str, str],
        start: datetime,
        end: datetime,
    ) -> list[dict[str, Any]]:
        key = self._metric_key(namespace, metric_name, dimensions)
        return self._metric_data.get(key, [])

    def lookup_cloudtrail_events(self, resource_arn: str, start: datetime, end: datetime) -> list[dict[str, Any]]:
        return self._cloudtrail_events.get(resource_arn, [])

    def get_bucket_public_access(self, bucket_name: str) -> bool:
        resource = self._resources.get(f"arn:aws:s3:::{bucket_name}")
        if resource is None:
            return False
        return bool(resource.attributes.get("is_public", False))

    def get_guardduty_findings(self, severity_threshold: float = 4.0) -> list[dict[str, Any]]:
        return [
            finding for finding in self._guardduty_findings if finding.get("severity", 0.0) >= severity_threshold
        ]

    # ---------------- test/dev helpers (not part of either Protocol) ----------------

    def seed_metric_data(
        self,
        namespace: str,
        metric_name: str,
        dimensions: dict[str, str],
        datapoints: list[dict[str, Any]],
    ) -> None:
        """Populate `get_metric_data` results for a test scenario -- e.g. a
        CPU utilization series climbing toward 95% over 10 minutes.
        """
        key = self._metric_key(namespace, metric_name, dimensions)
        self._metric_data[key] = datapoints

    def seed_cloudtrail_events(self, resource_arn: str, events: list[dict[str, Any]]) -> None:
        """Populate `lookup_cloudtrail_events` results for a specific
        resource ARN -- e.g. an `UpdateFunctionCode` event just before a
        Lambda error spike, so the Troubleshooting Agent has something to
        correlate against.
        """
        self._cloudtrail_events[resource_arn] = events

    def seed_guardduty_findings(self, findings: list[dict[str, Any]]) -> None:
        """Populate `get_guardduty_findings` results. Each finding dict
        should include a `"severity"` key (float) so the threshold filter
        in `get_guardduty_findings` behaves like the real API.
        """
        self._guardduty_findings = findings

    @staticmethod
    def _metric_key(namespace: str, metric_name: str, dimensions: dict[str, str]) -> str:
        """Deterministic cache key for a metric query -- sorted so the same
        dimensions in a different order still hit the same seeded data.
        """
        return f"{namespace}:{metric_name}:{sorted(dimensions.items())}"

    # ---------------- IMutatingAWSTools ----------------

    def reboot_instance(self, instance_id: str) -> None:
        self.mutation_log.append({"action": "reboot_instance", "instance_id": instance_id})

    def start_instance(self, instance_id: str) -> None:
        self.mutation_log.append({"action": "start_instance", "instance_id": instance_id})

    def scale_out(self, auto_scaling_group_name: str, increment: int) -> None:
        self.mutation_log.append(
            {"action": "scale_out", "auto_scaling_group_name": auto_scaling_group_name, "increment": increment}
        )

    def revoke_public_access(self, bucket_name: str) -> None:
        arn = f"arn:aws:s3:::{bucket_name}"
        if arn in self._resources:
            self._resources[arn].attributes["is_public"] = False
        self.mutation_log.append({"action": "revoke_public_access", "bucket_name": bucket_name})

    def detach_overly_permissive_policy(self, role_name: str, policy_arn: str) -> None:
        self.mutation_log.append(
            {"action": "detach_overly_permissive_policy", "role_name": role_name, "policy_arn": policy_arn}
        )

    def rollback_function_version(self, function_name: str, target_version: str) -> None:
        self.mutation_log.append(
            {
                "action": "rollback_function_version",
                "function_name": function_name,
                "target_version": target_version,
            }
        )

    def increase_storage_allocation(self, db_instance_identifier: str, new_allocated_storage_gb: int) -> None:
        self.mutation_log.append(
            {
                "action": "increase_storage_allocation",
                "db_instance_identifier": db_instance_identifier,
                "new_allocated_storage_gb": new_allocated_storage_gb,
            }
        )

    def reset_desired_capacity(self, auto_scaling_group_name: str, desired_capacity: int) -> None:
        self.mutation_log.append(
            {
                "action": "reset_desired_capacity",
                "auto_scaling_group_name": auto_scaling_group_name,
                "desired_capacity": desired_capacity,
            }
        )
