"""Evidence and AgentStep -- the append-only audit primitives."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from cloudops_ai.domain.enums import AgentName


def _utcnow() -> datetime:
    """Single source of truth for 'now', timezone-aware UTC."""
    return datetime.now(timezone.utc)


class Evidence(BaseModel):
    """A single piece of evidence gathered by an investigative agent."""

    evidence_id: str = Field(description="Stable ID (e.g. a ULID) for referencing this evidence elsewhere")
    agent: AgentName = Field(description="Which agent gathered this evidence")
    source: str = Field(
        description="Where it came from, e.g. 'cloudwatch:GetMetricData', 'cloudtrail:LookupEvents'"
    )
    summary: str = Field(description="One-sentence, human-readable summary of what this evidence shows")
    data: dict[str, Any] = Field(default_factory=dict, description="Raw or lightly-processed payload")
    collected_at: datetime = Field(default_factory=_utcnow)


class AgentStep(BaseModel):
    """One entry in the incident's audit trail: one agent's reasoning and
    actions during one pass through the graph."""

    step_id: str = Field(description="Stable ID for this step")
    agent: AgentName
    started_at: datetime = Field(default_factory=_utcnow)
    completed_at: datetime | None = Field(
        default=None, description="Set when the node finishes; None while the step is in flight"
    )
    reasoning: str = Field(description="The agent's own explanation of its conclusion, for human review")
    tool_calls: list[str] = Field(
        default_factory=list,
        description="Names of tools invoked during this step, e.g. ['cloudwatch.get_metric_data'].",
    )
    evidence_ids: list[str] = Field(
        default_factory=list, description="Evidence.evidence_id values this step produced or relied on"
    )

    def mark_completed(self) -> None:
        """Stamp completion time. Called by the graph runner, not the agent itself."""
        self.completed_at = _utcnow()
