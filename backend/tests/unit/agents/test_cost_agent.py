"""Unit tests for the Cost Agent node."""

from __future__ import annotations

from cloudops_ai.adapters.mock.mock_aws_gateway import MockAWSGateway
from cloudops_ai.agents.cost_agent import make_cost_node
from cloudops_ai.domain.enums import IncidentType, TriggerSource
from cloudops_ai.domain.models.incident import IncidentState


def _incident(incident_type: IncidentType) -> IncidentState:
    return IncidentState(
        incident_id="incident-1",
        trigger_source=TriggerSource.SCHEDULED_SCAN,
        incident_type=incident_type,
    )


def test_high_billing_honestly_flags_missing_cost_explorer_adapter() -> None:
    gateway = MockAWSGateway()
    incident = _incident(IncidentType.HIGH_BILLING)

    node = make_cost_node(gateway)
    result = node({"incident": incident})
    updated = result["incident"]

    assert updated.evidence == []  # nothing fabricated
    assert "No Cost Explorer adapter exists yet" in updated.agent_trace[0].reasoning
    assert len(updated.agent_trace) == 1


def test_no_op_for_unrelated_incident_type() -> None:
    gateway = MockAWSGateway()
    incident = _incident(IncidentType.EC2_HIGH_CPU)

    node = make_cost_node(gateway)
    result = node({"incident": incident})

    assert "no investigation logic" in result["incident"].agent_trace[0].reasoning
