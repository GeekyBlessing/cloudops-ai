"""Unit tests for the Evidence and AgentStep audit primitives."""

from __future__ import annotations

from cloudops_ai.domain.enums import AgentName
from cloudops_ai.domain.models.evidence import AgentStep, Evidence


def test_evidence_defaults_have_timezone_aware_timestamp() -> None:
    ev = Evidence(evidence_id="ev-1", agent=AgentName.MONITORING, source="cloudwatch", summary="CPU at 95%")
    assert ev.collected_at.tzinfo is not None


def test_agent_step_starts_without_completion_timestamp() -> None:
    step = AgentStep(step_id="step-1", agent=AgentName.COORDINATOR, reasoning="Classifying incident")
    assert step.completed_at is None


def test_agent_step_mark_completed_sets_timestamp_after_start() -> None:
    step = AgentStep(step_id="step-1", agent=AgentName.COORDINATOR, reasoning="Classifying incident")
    step.mark_completed()
    assert step.completed_at is not None
    assert step.completed_at >= step.started_at
