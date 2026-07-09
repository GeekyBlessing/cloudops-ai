"""Remediation planning and execution models -- the safety-critical core.

A RemediationPlan can only execute live if it carries a valid, matching
ApprovalToken. Enforced by RemediationPlan.can_execute_live().
"""

from __future__ import annotations

import hashlib
import hmac
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field, model_validator

from cloudops_ai.domain.enums import RemediationStatus


class ApprovalToken(BaseModel):
    """Proof that a specific human approved a specific remediation plan."""

    plan_id: str
    approved_by: str = Field(description="Identity of the human approver, e.g. an email or SSO subject")
    approved_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    signature: str = Field(description="HMAC-SHA256 of plan_id, signed with the approval service's secret key")

    @staticmethod
    def sign(plan_id: str, secret_key: bytes) -> str:
        return hmac.new(secret_key, plan_id.encode("utf-8"), hashlib.sha256).hexdigest()

    def verify(self, secret_key: bytes) -> bool:
        expected = self.sign(self.plan_id, secret_key)
        return hmac.compare_digest(expected, self.signature)


class RemediationAction(BaseModel):
    """A single concrete AWS API call the plan wants to make."""

    action_name: str = Field(description="e.g. 'reboot_instance', 'update_bucket_acl'")
    target_arn: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    is_reversible: bool = Field(description="Whether this action has a known, automatable undo path")


class RemediationPlan(BaseModel):
    """A proposed (and eventually executed) remediation for one incident."""

    plan_id: str
    incident_id: str
    actions: list[RemediationAction] = Field(min_length=1)
    status: RemediationStatus = RemediationStatus.NOT_STARTED
    requires_approval: bool = Field(
        description="True for any plan containing a mutating action while REMEDIATION_MODE=live."
    )
    approval: ApprovalToken | None = None
    rationale: str = Field(description="Coordinator's explanation of why this plan was chosen")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @model_validator(mode="after")
    def _approval_must_match_plan(self) -> RemediationPlan:
        if self.approval is not None and self.approval.plan_id != self.plan_id:
            raise ValueError(
                f"Approval token is for plan {self.approval.plan_id!r}, but this is plan {self.plan_id!r}"
            )
        return self

    def can_execute_live(self, secret_key: bytes) -> bool:
        """The single gate the Remediation Executor must pass before doing
        anything irreversible. Fails closed."""
        if not self.requires_approval:
            return True
        if self.status != RemediationStatus.APPROVED:
            return False
        if self.approval is None:
            return False
        return self.approval.verify(secret_key)
