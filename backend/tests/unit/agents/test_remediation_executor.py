"""Unit tests for the Remediation Executor node -- the safety-critical
last link in the chain from "Coordinator proposed a plan" to "AWS actually
got mutated."
"""

from __future__ import annotations

from cloudops_ai.agents.remediation_executor import _ACTION_INVOKERS, make_remediation_executor_node
from cloudops_ai.domain.enums import RemediationStatus, TriggerSource
from cloudops_ai.domain.models.incident import IncidentState
from cloudops_ai.domain.models.remediation import ApprovalToken, RemediationAction, RemediationPlan
from cloudops_ai.domain.policies.remediation_policy import REMEDIATION_POLICY
from cloudops_ai.tools.dry_run.dry_run_adapter import DryRunAWSTools

SECRET_KEY = b"test-secret-key"


def _incident_with_plan(status: RemediationStatus, with_valid_approval: bool) -> IncidentState:
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
        status=status,
    )
    if with_valid_approval:
        signature = ApprovalToken.sign(plan.plan_id, SECRET_KEY)
        plan.approval = ApprovalToken(plan_id=plan.plan_id, approved_by="toriola@example.com", signature=signature)

    incident = IncidentState(incident_id="incident-1", trigger_source=TriggerSource.CLOUDWATCH_ALARM)
    incident.proposed_remediation = plan
    return incident


def test_executor_runs_approved_plan_and_marks_verified() -> None:
    incident = _incident_with_plan(RemediationStatus.APPROVED, with_valid_approval=True)
    dry_run_tools = DryRunAWSTools()

    node = make_remediation_executor_node(mutating_tools=dry_run_tools, secret_key=SECRET_KEY)
    result = node({"incident": incident})
    updated = result["incident"]

    assert updated.proposed_remediation.status == RemediationStatus.VERIFIED
    assert updated.remediation_status == RemediationStatus.VERIFIED
    assert dry_run_tools.actions_logged == [{"action": "reboot_instance", "instance_id": "i-0abcd1234"}]
    assert updated.agent_trace[-1].agent.value == "remediation_executor"


def test_executor_refuses_to_execute_without_approval() -> None:
    incident = _incident_with_plan(RemediationStatus.AWAITING_APPROVAL, with_valid_approval=False)
    dry_run_tools = DryRunAWSTools()

    node = make_remediation_executor_node(mutating_tools=dry_run_tools, secret_key=SECRET_KEY)
    result = node({"incident": incident})
    updated = result["incident"]

    assert dry_run_tools.actions_logged == []
    assert updated.proposed_remediation.status == RemediationStatus.AWAITING_APPROVAL


def test_executor_refuses_to_execute_with_forged_approval() -> None:
    plan = RemediationPlan(
        plan_id="plan-2",
        incident_id="incident-1",
        actions=[
            RemediationAction(
                action_name="reboot_instance",
                target_arn="arn:aws:ec2:us-east-1:123456789012:instance/i-0abcd1234",
                is_reversible=True,
            )
        ],
        requires_approval=True,
        rationale="test",
        status=RemediationStatus.APPROVED,
        approval=ApprovalToken(plan_id="plan-2", approved_by="attacker@example.com", signature="forged"),
    )
    incident = IncidentState(incident_id="incident-1", trigger_source=TriggerSource.CLOUDWATCH_ALARM)
    incident.proposed_remediation = plan
    dry_run_tools = DryRunAWSTools()

    node = make_remediation_executor_node(mutating_tools=dry_run_tools, secret_key=SECRET_KEY)
    node({"incident": incident})

    assert dry_run_tools.actions_logged == []


def test_executor_handles_no_proposed_plan_gracefully() -> None:
    incident = IncidentState(incident_id="incident-2", trigger_source=TriggerSource.MANUAL)
    dry_run_tools = DryRunAWSTools()

    node = make_remediation_executor_node(mutating_tools=dry_run_tools, secret_key=SECRET_KEY)
    result = node({"incident": incident})

    assert result["incident"].proposed_remediation is None
    assert dry_run_tools.actions_logged == []
    assert len(result["incident"].agent_trace) == 1


def test_every_policy_allowed_action_has_an_executor_mapping() -> None:
    """Guards against the exact drift this module's docstring warns about:
    a policy entry naming an action the executor doesn't know how to run.
    """
    all_allowed_actions = {
        action for entry in REMEDIATION_POLICY.values() for action in entry.allowed_actions
    }
    missing = all_allowed_actions - set(_ACTION_INVOKERS.keys())
    assert not missing, f"Policy table allows actions with no executor mapping: {missing}"


def test_every_executor_mapping_corresponds_to_a_real_dry_run_method() -> None:
    """The inverse check: every action this module claims to be able to
    execute must actually exist as a method on IMutatingAWSTools
    implementations (using DryRunAWSTools as the reference implementation).
    """
    dry_run_tools = DryRunAWSTools()
    missing = [name for name in _ACTION_INVOKERS if not hasattr(dry_run_tools, name)]
    assert not missing, f"Executor mapping references methods DryRunAWSTools doesn't have: {missing}"


def test_executor_revokes_public_access_and_extracts_bucket_name_from_arn() -> None:
    """Covers the one action-invoker branch none of the tests above exercise
    (revoke_public_access), which is also the only one that routes target_arn
    through _extract_bucket_name instead of _extract_instance_id.
    """
    plan = RemediationPlan(
        plan_id="plan-3",
        incident_id="incident-1",
        actions=[
            RemediationAction(
                action_name="revoke_public_access",
                target_arn="arn:aws:s3:::my-public-bucket",
                is_reversible=True,
            )
        ],
        requires_approval=True,
        rationale="Bucket policy allows public read",
        status=RemediationStatus.APPROVED,
    )
    signature = ApprovalToken.sign(plan.plan_id, SECRET_KEY)
    plan.approval = ApprovalToken(plan_id=plan.plan_id, approved_by="toriola@example.com", signature=signature)
    incident = IncidentState(incident_id="incident-3", trigger_source=TriggerSource.CLOUDWATCH_ALARM)
    incident.proposed_remediation = plan
    dry_run_tools = DryRunAWSTools()
    node = make_remediation_executor_node(mutating_tools=dry_run_tools, secret_key=SECRET_KEY)
    result = node({"incident": incident})
    updated = result["incident"]
    assert updated.proposed_remediation.status == RemediationStatus.VERIFIED
    assert dry_run_tools.actions_logged == [
        {"action": "revoke_public_access", "bucket_name": "my-public-bucket"}
    ]


def test_executor_marks_plan_failed_when_action_has_no_executor_mapping() -> None:
    """RemediationAction.action_name is a plain str, not an enum -- a policy
    entry could name an action this module has no invoker for. That's a code
    bug (guarded against by test_every_policy_allowed_action_has_an_executor_mapping
    above), but if it ever happened at runtime this proves the executor fails
    closed: the RuntimeError is caught, the plan/incident flip to FAILED, and
    nothing is silently swallowed.
    """
    plan = RemediationPlan(
        plan_id="plan-4",
        incident_id="incident-1",
        actions=[
            RemediationAction(
                action_name="totally_unsupported_action",
                target_arn="arn:aws:ec2:us-east-1:123456789012:instance/i-0abcd1234",
                is_reversible=True,
            )
        ],
        requires_approval=True,
        rationale="test",
        status=RemediationStatus.APPROVED,
    )
    signature = ApprovalToken.sign(plan.plan_id, SECRET_KEY)
    plan.approval = ApprovalToken(plan_id=plan.plan_id, approved_by="toriola@example.com", signature=signature)
    incident = IncidentState(incident_id="incident-4", trigger_source=TriggerSource.CLOUDWATCH_ALARM)
    incident.proposed_remediation = plan
    dry_run_tools = DryRunAWSTools()
    node = make_remediation_executor_node(mutating_tools=dry_run_tools, secret_key=SECRET_KEY)
    result = node({"incident": incident})
    updated = result["incident"]
    assert updated.proposed_remediation.status == RemediationStatus.FAILED
    assert updated.remediation_status == RemediationStatus.FAILED
    assert dry_run_tools.actions_logged == []
    assert "No executor mapping" in updated.agent_trace[-1].reasoning
