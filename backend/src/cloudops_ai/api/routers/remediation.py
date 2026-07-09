"""`/remediation` router.

Two operations: approve and reject. Approving a plan signs an ApprovalToken,
marks it APPROVED, and synchronously runs the Remediation Executor --
see services/approval_service.py for why those two steps are combined here.
This is the API surface for the human-in-the-loop gate described throughout
/docs/ARCHITECTURE.md: nothing upstream of this router can make AWS mutate
anything without a POST to this exact endpoint.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from cloudops_ai.api.dependencies import get_incident_repository, get_mutating_aws_tools
from cloudops_ai.core.config import Settings, get_settings
from cloudops_ai.domain.enums import RemediationStatus
from cloudops_ai.domain.models.incident import IncidentState
from cloudops_ai.repositories.interfaces import IIncidentRepository
from cloudops_ai.services.approval_service import approve_and_execute, reject_remediation
from cloudops_ai.tools.interfaces import IMutatingAWSTools

router = APIRouter(prefix="/remediation", tags=["remediation"])


class ApprovalRequest(BaseModel):
    """Who is approving this plan -- recorded on the ApprovalToken itself,
    so the audit trail says who authorized a given AWS mutation, not just
    that "someone" did.
    """

    approved_by: str = Field(description="Identity of the human approver, e.g. an email or SSO subject")


def _get_incident_or_404(incident_id: str, repo: IIncidentRepository) -> IncidentState:
    incident = repo.get(incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail=f"No incident with id {incident_id!r}")
    return incident


def _require_awaiting_approval(incident: IncidentState) -> None:
    plan = incident.proposed_remediation
    if plan is None:
        raise HTTPException(status_code=400, detail="This incident has no proposed remediation plan")
    if plan.status != RemediationStatus.AWAITING_APPROVAL:
        raise HTTPException(
            status_code=409,
            detail=f"Plan status is {plan.status.value!r}, not 'awaiting_approval' -- it may already "
            "have been approved, rejected, or executed",
        )


@router.post("/{incident_id}/approve", response_model=IncidentState)
def approve(
    incident_id: str,
    request: ApprovalRequest,
    repo: IIncidentRepository = Depends(get_incident_repository),
    settings: Settings = Depends(get_settings),
    mutating_tools: IMutatingAWSTools = Depends(get_mutating_aws_tools),
) -> IncidentState:
    """Approve and immediately execute the incident's proposed remediation plan."""
    incident = _get_incident_or_404(incident_id, repo)
    _require_awaiting_approval(incident)

    updated = approve_and_execute(
        incident, approved_by=request.approved_by, settings=settings, mutating_tools=mutating_tools
    )
    repo.save(updated)
    return updated


@router.post("/{incident_id}/reject", response_model=IncidentState)
def reject(
    incident_id: str,
    repo: IIncidentRepository = Depends(get_incident_repository),
) -> IncidentState:
    """Reject the incident's proposed remediation plan. No AWS call is made."""
    incident = _get_incident_or_404(incident_id, repo)
    _require_awaiting_approval(incident)

    updated = reject_remediation(incident)
    repo.save(updated)
    return updated
