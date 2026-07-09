"""Unit tests for the approval service -- the orchestration layer between
the /remediation router and the domain/agents underneath.
"""

from __future__ import annotations

import pytest

from cloudops_ai.core.config import Settings
from cloudops_ai.domain.enums import RemediationStatus, TriggerSource
from cloudops_ai.domain.models.incident import IncidentState
from cloudops_ai.domain.models.remediation import RemediationAction, RemediationPlan
from cloudops_ai.services.approval_service import approve_and_execute, reject_remediation
from cloudops_ai.tools.dry_run.dry_run_adapter import DryRunAWSTools


def _incident_awaiting_approval() -> IncidentState:
    plan = RemediationPlan(
        plan_id="plan-1",
        incident_id="incident-1",
        actions=[
            RemediationAction(
                action_name="reboot_instance",
                target_arn="arn:aws:ec2:us-east-1:123456789012:instance/i-0abcd1234",
                is_reversible=True,
            )
        ],
        requires_approval=True,
        rationale="CPU sustained above threshold",
        status=RemediationStatus.AWAITING_APPROVAL,
    )
    incident = IncidentState(incident_id="incident-1", trigger_source=TriggerSource.CLOUDWATCH_ALARM)
    incident.proposed_remediation = plan
    return incident


def test_approve_and_execute_signs_token_and_runs_executor() -> None:
    incident = _incident_awaiting_approval()
    settings = Settings(approval_secret_key="test-secret-key")
    dry_run_tools = DryRunAWSTools()

    updated = approve_and_execute(
        incident, approved_by="toriola@example.com", settings=settings, mutating_tools=dry_run_tools
    )

    assert updated.proposed_remediation.approval is not None
    assert updated.proposed_remediation.approval.approved_by == "toriola@example.com"
    assert updated.proposed_remediation.approval.verify(settings.approval_secret_key.encode("utf-8"))
    assert updated.proposed_remediation.status == RemediationStatus.VERIFIED
    assert updated.remediation_status == RemediationStatus.VERIFIED
    assert dry_run_tools.actions_logged  # the executor actually ran


def test_approve_and_execute_raises_for_incident_with_no_plan() -> None:
    incident = IncidentState(incident_id="incident-2", trigger_source=TriggerSource.MANUAL)
    settings = Settings(approval_secret_key="test-secret-key")

    with pytest.raises(ValueError):
        approve_and_execute(incident, approved_by="toriola@example.com", settings=settings, mutating_tools=DryRunAWSTools())


def test_reject_remediation_sets_status_rejected_without_calling_aws() -> None:
    incident = _incident_awaiting_approval()

    updated = reject_remediation(incident)

    assert updated.proposed_remediation.status == RemediationStatus.REJECTED
    assert updated.remediation_status == RemediationStatus.REJECTED
    assert updated.proposed_remediation.approval is None


def test_reject_remediation_raises_for_incident_with_no_plan() -> None:
    incident = IncidentState(incident_id="incident-3", trigger_source=TriggerSource.MANUAL)

    with pytest.raises(ValueError):
        reject_remediation(incident)
