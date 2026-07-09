"""Approval workflow: signs and verifies ApprovalTokens, and orchestrates
running the Remediation Executor once a human approves a plan.

This is the first file in services/ -- see the package docstring. Routers
(api/routers/remediation.py) call these two functions rather than
manipulating RemediationPlan/IncidentState status fields directly.
"""

from __future__ import annotations

from cloudops_ai.agents.remediation_executor import make_remediation_executor_node
from cloudops_ai.core.config import Settings
from cloudops_ai.domain.enums import RemediationStatus
from cloudops_ai.domain.models.incident import IncidentState
from cloudops_ai.domain.models.remediation import ApprovalToken
from cloudops_ai.tools.interfaces import IMutatingAWSTools


def approve_and_execute(
    incident: IncidentState,
    approved_by: str,
    settings: Settings,
    mutating_tools: IMutatingAWSTools,
) -> IncidentState:
    """Sign an ApprovalToken for the incident's proposed plan, mark it
    APPROVED, then immediately run the Remediation Executor.

    Combining "approve" and "execute" into one call is a deliberate
    simplification for this build step -- a real deployment might separate
    them (approve now, a worker picks up execution later), but doing both
    synchronously here means the API response tells the caller exactly what
    happened, which matters a lot for a portfolio demo and isn't wrong for
    a real system either, just less decoupled.

    The caller (the /remediation/{id}/approve route) is responsible for
    checking `incident.proposed_remediation` exists and is in
    AWAITING_APPROVAL before calling this -- this function trusts that's
    already been verified and will raise on a `None` plan rather than
    silently no-op, since reaching this function with no plan is a bug in
    the caller, not a normal outcome to handle gracefully.
    """
    plan = incident.proposed_remediation
    if plan is None:
        raise ValueError(f"Incident {incident.incident_id} has no proposed_remediation to approve")

    secret_key = settings.approval_secret_key.encode("utf-8")
    signature = ApprovalToken.sign(plan.plan_id, secret_key)
    plan.approval = ApprovalToken(plan_id=plan.plan_id, approved_by=approved_by, signature=signature)
    plan.status = RemediationStatus.APPROVED
    incident.remediation_status = RemediationStatus.APPROVED

    executor_node = make_remediation_executor_node(mutating_tools=mutating_tools, secret_key=secret_key)
    result = executor_node({"incident": incident})
    return result["incident"]


def reject_remediation(incident: IncidentState) -> IncidentState:
    """Mark the incident's proposed plan REJECTED. No AWS call is ever made
    -- this function's entire job is to record a human's "no" and stop.
    """
    plan = incident.proposed_remediation
    if plan is None:
        raise ValueError(f"Incident {incident.incident_id} has no proposed_remediation to reject")

    plan.status = RemediationStatus.REJECTED
    incident.remediation_status = RemediationStatus.REJECTED
    return incident
