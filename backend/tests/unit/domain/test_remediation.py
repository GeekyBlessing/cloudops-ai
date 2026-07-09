"""Unit tests for the remediation safety invariants -- the most important
tests in the codebase."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from cloudops_ai.domain.enums import RemediationStatus
from cloudops_ai.domain.models.remediation import ApprovalToken, RemediationAction, RemediationPlan


def _make_plan(secret_key: bytes, **overrides: object) -> RemediationPlan:
    defaults: dict[str, object] = dict(
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
        rationale="CPU sustained above 95% for 10 minutes with no active deploy in progress",
    )
    defaults.update(overrides)
    return RemediationPlan(**defaults)  # type: ignore[arg-type]


def test_plan_without_approval_cannot_execute_live(approval_secret_key: bytes) -> None:
    plan = _make_plan(approval_secret_key)
    assert plan.can_execute_live(approval_secret_key) is False


def test_plan_with_valid_approval_can_execute_live(approval_secret_key: bytes) -> None:
    plan = _make_plan(approval_secret_key, status=RemediationStatus.APPROVED)
    signature = ApprovalToken.sign(plan.plan_id, approval_secret_key)
    plan.approval = ApprovalToken(plan_id=plan.plan_id, approved_by="toriola@example.com", signature=signature)
    assert plan.can_execute_live(approval_secret_key) is True


def test_plan_with_forged_signature_is_rejected(approval_secret_key: bytes) -> None:
    plan = _make_plan(approval_secret_key, status=RemediationStatus.APPROVED)
    plan.approval = ApprovalToken(
        plan_id=plan.plan_id, approved_by="toriola@example.com", signature="forged-signature"
    )
    assert plan.can_execute_live(approval_secret_key) is False


def test_plan_approved_but_signed_with_wrong_key_is_rejected(approval_secret_key: bytes) -> None:
    plan = _make_plan(approval_secret_key, status=RemediationStatus.APPROVED)
    wrong_key = b"a-different-secret-key"
    signature = ApprovalToken.sign(plan.plan_id, wrong_key)
    plan.approval = ApprovalToken(plan_id=plan.plan_id, approved_by="toriola@example.com", signature=signature)
    assert plan.can_execute_live(approval_secret_key) is False


def test_approval_for_a_different_plan_is_rejected_at_construction(approval_secret_key: bytes) -> None:
    signature = ApprovalToken.sign("some-other-plan", approval_secret_key)
    mismatched_approval = ApprovalToken(
        plan_id="some-other-plan", approved_by="toriola@example.com", signature=signature
    )
    with pytest.raises(ValidationError):
        _make_plan(approval_secret_key, approval=mismatched_approval)


def test_plan_requires_at_least_one_action(approval_secret_key: bytes) -> None:
    with pytest.raises(ValidationError):
        RemediationPlan(
            plan_id="plan-2",
            incident_id="incident-1",
            actions=[],
            requires_approval=False,
            rationale="no-op",
        )


def test_plan_not_requiring_approval_can_execute_without_a_token(approval_secret_key: bytes) -> None:
    plan = _make_plan(approval_secret_key, requires_approval=False)
    assert plan.can_execute_live(approval_secret_key) is True
