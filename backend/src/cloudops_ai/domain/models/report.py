"""Final compiled incident report."""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field

from cloudops_ai.domain.enums import IncidentType, RemediationStatus, Severity


class TimelineEntry(BaseModel):
    """One row in the incident timeline shown on the dashboard."""

    timestamp: datetime
    label: str = Field(description="Short label, e.g. 'Detected', 'Root cause identified'")
    detail: str = Field(description="Longer human-readable description of this timeline event")


class IncidentReport(BaseModel):
    """The final, human-readable artifact produced for every incident."""

    incident_id: str
    incident_type: IncidentType
    severity: Severity
    summary: str = Field(description="2-4 sentence executive summary")
    root_cause: str
    remediation_taken: str
    remediation_status: RemediationStatus
    supporting_evidence_ids: list[str] = Field(default_factory=list)
    timeline: list[TimelineEntry] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    generated_by: str = Field(default="coordinator_agent")
