"""IncidentState -- the single shared state object that flows through every
node of the LangGraph agent graph.

This is the most important model in the codebase: every agent reads from and
appends to this object. See /docs/ARCHITECTURE.md section 4.2 for the design
rationale (append-only evidence/trace, not overwritten fields).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from cloudops_ai.domain.enums import AgentName, IncidentType, RemediationStatus, Severity, TriggerSource
from cloudops_ai.domain.models.evidence import AgentStep, Evidence
from cloudops_ai.domain.models.remediation import RemediationPlan
from cloudops_ai.domain.models.report import IncidentReport
from cloudops_ai.domain.models.resource import ResourceRef


class IncidentState(BaseModel):
    """Shared state threaded through the LangGraph StateGraph.

    Design note: LangGraph is happy to work with a plain TypedDict, but we
    use a Pydantic model instead so that (a) every field is validated on
    every node's return value -- an agent node that tries to return a
    malformed evidence list fails loudly at the model boundary instead of
    corrupting state silently, and (b) we get `.model_dump_json()` for free
    when persisting checkpoints and the final report to DynamoDB.
    """

    incident_id: str
    trigger_source: TriggerSource
    incident_type: IncidentType = Field(
        default=IncidentType.UNKNOWN,
        description="Set by the Coordinator after classification; UNKNOWN until then.",
    )
    severity: Severity | None = Field(default=None, description="Set by the Coordinator alongside incident_type")
    affected_resources: list[ResourceRef] = Field(default_factory=list)
    raw_trigger_payload: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "The original trigger event, if this incident came from something richer than a "
            "manual API call -- e.g. a CloudWatch Alarm State Change or GuardDuty Finding event "
            "as delivered via EventBridge/SQS (see services/sqs_incident_poller.py). Empty for "
            "MANUAL incidents created through the dashboard/API, which have nothing richer to "
            "attach. The Coordinator's classify_node reads this to actually have something to "
            "classify beyond the trigger_source enum -- see that module's docstring for why this "
            "field exists at all."
        ),
    )

    # --- Append-only audit trail. Agents call the helper methods below, never
    # reassign these lists directly. ---
    evidence: list[Evidence] = Field(default_factory=list)
    agent_trace: list[AgentStep] = Field(default_factory=list)

    root_cause_hypothesis: str | None = None
    proposed_remediation: RemediationPlan | None = None
    remediation_status: RemediationStatus = RemediationStatus.NOT_STARTED

    report: IncidentReport | None = Field(default=None, description="Populated by the Coordinator's final step")

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def add_evidence(self, item: Evidence) -> None:
        """Append new evidence and bump `updated_at`.

        Every agent should call this rather than mutating `.evidence`
        directly, so `updated_at` can never drift out of sync with the
        actual last change -- small thing, but it's exactly the kind of
        "everyone has to remember to do the second half of the update" bug
        that creeps into shared-state systems over time.
        """
        self.evidence.append(item)
        self.updated_at = datetime.now(timezone.utc)

    def add_agent_step(self, step: AgentStep) -> None:
        """Append a step to the audit trail. See `add_evidence` for why this
        is a method rather than direct list mutation.
        """
        self.agent_trace.append(step)
        self.updated_at = datetime.now(timezone.utc)

    def evidence_from(self, agent: AgentName) -> list[Evidence]:
        """Convenience accessor: all evidence gathered by one specific agent.

        Used by the Coordinator's merge step, which needs to reason about
        each specialist's contribution separately before synthesizing a
        remediation plan.
        """
        return [item for item in self.evidence if item.agent == agent]
