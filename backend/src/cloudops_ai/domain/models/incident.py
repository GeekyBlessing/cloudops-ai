"""IncidentState -- the single shared state object that flows through every
node of the LangGraph agent graph."""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field

from cloudops_ai.domain.enums import AgentName, IncidentType, RemediationStatus, Severity, TriggerSource
from cloudops_ai.domain.models.evidence import AgentStep, Evidence
from cloudops_ai.domain.models.remediation import RemediationPlan
from cloudops_ai.domain.models.report import IncidentReport
from cloudops_ai.domain.models.resource import ResourceRef


class IncidentState(BaseModel):
    """Shared state threaded through the LangGraph StateGraph."""

    incident_id: str
    trigger_source: TriggerSource
    incident_type: IncidentType = Field(default=IncidentType.UNKNOWN)
    severity: Severity | None = None
    affected_resources: list[ResourceRef] = Field(default_factory=list)

    evidence: list[Evidence] = Field(default_factory=list)
    agent_trace: list[AgentStep] = Field(default_factory=list)

    root_cause_hypothesis: str | None = None
    proposed_remediation: RemediationPlan | None = None
    remediation_status: RemediationStatus = RemediationStatus.NOT_STARTED

    report: IncidentReport | None = None

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def add_evidence(self, item: Evidence) -> None:
        """Append new evidence and bump updated_at -- never assign to .evidence directly."""
        self.evidence.append(item)
        self.updated_at = datetime.now(timezone.utc)

    def add_agent_step(self, step: AgentStep) -> None:
        """Append a step to the audit trail -- never assign to .agent_trace directly."""
        self.agent_trace.append(step)
        self.updated_at = datetime.now(timezone.utc)

    def evidence_from(self, agent: AgentName) -> list[Evidence]:
        """All evidence gathered by one specific agent."""
        return [item for item in self.evidence if item.agent == agent]
