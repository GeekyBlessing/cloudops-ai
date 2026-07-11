"""Unit tests for the Monitoring Agent node."""

from __future__ import annotations

from cloudops_ai.adapters.mock.mock_aws_gateway import MockAWSGateway
from cloudops_ai.agents.monitoring_agent import make_monitoring_node
from cloudops_ai.domain.enums import AgentName, TriggerSource
from cloudops_ai.domain.models.incident import IncidentState


def test_monitoring_node_skips_metric_fetch_when_incident_has_no_affected_resource() -> None:
    """Every existing exercise of this node (via test_coordinator.py /
    test_graph.py) attaches an affected resource before Monitoring runs, so
    this early-return branch -- for an incident that reaches this node with
    no affected resource yet -- was never covered.
    """
    incident = IncidentState(incident_id="incident-1", trigger_source=TriggerSource.CLOUDWATCH_ALARM)
    assert incident.affected_resources == []
    gateway = MockAWSGateway()
    node = make_monitoring_node(aws_tools=gateway)

    result = node({"incident": incident})

    updated = result["incident"]
    assert len(updated.agent_trace) == 1
    step = updated.agent_trace[-1]
    assert step.agent == AgentName.MONITORING
    assert "No affected resource" in step.reasoning
    assert step.tool_calls == []
