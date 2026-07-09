"""Unit tests for IncidentState, the shared LangGraph state contract."""

from __future__ import annotations

from cloudops_ai.domain.enums import AgentName, TriggerSource
from cloudops_ai.domain.models.evidence import Evidence
from cloudops_ai.domain.models.incident import IncidentState


def test_add_evidence_appends_and_bumps_updated_at() -> None:
    state = IncidentState(incident_id="incident-1", trigger_source=TriggerSource.CLOUDWATCH_ALARM)
    before = state.updated_at
    state.add_evidence(
        Evidence(evidence_id="ev-1", agent=AgentName.MONITORING, source="cloudwatch", summary="CPU spike")
    )
    assert len(state.evidence) == 1
    assert state.updated_at >= before


def test_evidence_from_filters_by_agent() -> None:
    state = IncidentState(incident_id="incident-1", trigger_source=TriggerSource.CLOUDWATCH_ALARM)
    state.add_evidence(
        Evidence(evidence_id="ev-1", agent=AgentName.MONITORING, source="cloudwatch", summary="CPU spike")
    )
    state.add_evidence(
        Evidence(evidence_id="ev-2", agent=AgentName.SECURITY, source="iam", summary="Overly broad policy")
    )
    monitoring_evidence = state.evidence_from(AgentName.MONITORING)
    assert len(monitoring_evidence) == 1
    assert monitoring_evidence[0].evidence_id == "ev-1"


def test_new_incident_state_starts_with_no_evidence_or_trace() -> None:
    state = IncidentState(incident_id="incident-1", trigger_source=TriggerSource.MANUAL)
    assert state.evidence == []
    assert state.agent_trace == []
    assert state.report is None
