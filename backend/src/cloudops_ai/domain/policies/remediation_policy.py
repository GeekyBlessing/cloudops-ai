"""Remediation policy table -- the allow-list that constrains what the
Coordinator is permitted to propose for each incident type/severity.

This is the concrete mechanism behind /docs/ARCHITECTURE.md section 7's claim
that "the Coordinator cannot propose an action outside a policy table." The
Coordinator's LLM call can reason about and suggest anything it wants; only
actions present in this table are ever allowed to become a RemediationAction
that the Remediation Executor will accept. This keeps the safety boundary in
plain, reviewable Python data -- not inside a prompt that an LLM might not
reliably follow under all inputs.
"""

from __future__ import annotations

from dataclasses import dataclass

from cloudops_ai.domain.enums import IncidentType, Severity


@dataclass(frozen=True)
class PolicyEntry:
    """Allow-listed actions for one (incident_type, severity) pair."""

    allowed_actions: frozenset[str]
    requires_approval: bool = True
    max_actions_per_incident: int = 1


REMEDIATION_POLICY: dict[tuple[IncidentType, Severity], PolicyEntry] = {
    (IncidentType.EC2_HIGH_CPU, Severity.HIGH): PolicyEntry(
        allowed_actions=frozenset({"reboot_instance", "scale_out"}),
    ),
    (IncidentType.EC2_HIGH_CPU, Severity.CRITICAL): PolicyEntry(
        allowed_actions=frozenset({"reboot_instance", "scale_out"}),
        requires_approval=True,
    ),
    (IncidentType.EC2_DOWN, Severity.CRITICAL): PolicyEntry(
        allowed_actions=frozenset({"start_instance", "reboot_instance"}),
    ),
    (IncidentType.PUBLIC_S3_BUCKET, Severity.CRITICAL): PolicyEntry(
        # Only "revoke_public_access" -- IMutatingAWSTools has no separate
        # update_bucket_acl method (an earlier draft of this table listed one
        # that was never added to the interface; removed here rather than
        # left dangling, since a policy entry naming an action with no
        # executor mapping would be a silent no-op waiting to happen).
        allowed_actions=frozenset({"revoke_public_access"}),
    ),
    (IncidentType.IAM_MISCONFIGURATION, Severity.HIGH): PolicyEntry(
        allowed_actions=frozenset({"detach_overly_permissive_policy"}),
    ),
    (IncidentType.LAMBDA_ERRORS, Severity.HIGH): PolicyEntry(
        allowed_actions=frozenset({"rollback_function_version"}),
    ),
    (IncidentType.RDS_STORAGE_FULL, Severity.HIGH): PolicyEntry(
        allowed_actions=frozenset({"increase_storage_allocation"}),
    ),
    (IncidentType.AUTO_SCALING_FAILURE, Severity.HIGH): PolicyEntry(
        allowed_actions=frozenset({"reset_desired_capacity"}),
    ),
    # HIGH_BILLING has no mutating actions on purpose -- cost anomalies get a
    # recommendation in the report, never an automatic action.
}


def is_action_allowed(incident_type: IncidentType, severity: Severity, action_name: str) -> bool:
    """The single choke point every proposed RemediationAction must pass
    through before it can become part of a RemediationPlan.
    """
    entry = REMEDIATION_POLICY.get((incident_type, severity))
    if entry is None:
        return False
    return action_name in entry.allowed_actions
