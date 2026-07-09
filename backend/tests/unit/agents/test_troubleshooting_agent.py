"""Unit tests for the Troubleshooting Agent node."""

from __future__ import annotations

from datetime import datetime, timezone

from cloudops_ai.adapters.mock.mock_aws_gateway import MockAWSGateway
from cloudops_ai.agents.troubleshooting_agent import make_troubleshooting_node
from cloudops_ai.domain.enums import IncidentType, TriggerSource
from cloudops_ai.domain.models.incident import IncidentState
from cloudops_ai.domain.models.resource import ResourceRef


def _incident(incident_type: IncidentType, resources: list[ResourceRef]) -> IncidentState:
    return IncidentState(
        incident_id="incident-1",
        trigger_source=TriggerSource.CLOUDWATCH_ALARM,
        affected_resources=resources,
        incident_type=incident_type,
    )


def _lambda_resource() -> ResourceRef:
    return ResourceRef(
        arn="arn:aws:lambda:us-east-1:123456789012:function:my-function",
        resource_type="AWS::Lambda::Function",
        region="us-east-1",
        account_id="123456789012",
    )


def test_lambda_errors_with_deploy_event_hypothesizes_bad_release() -> None:
    function = _lambda_resource()
    gateway = MockAWSGateway(seed_resources=[function])
    now = datetime.now(timezone.utc)
    gateway.seed_metric_data(
        namespace="AWS/Lambda",
        metric_name="Errors",
        dimensions={"FunctionName": "my-function"},
        datapoints=[{"Timestamp": now.isoformat(), "Sum": 12.0}],
    )
    gateway.seed_cloudtrail_events(
        function.arn,
        [{"EventName": "UpdateFunctionCode", "EventTime": now.isoformat()}],
    )
    incident = _incident(IncidentType.LAMBDA_ERRORS, [function])

    node = make_troubleshooting_node(gateway)
    result = node({"incident": incident})
    updated = result["incident"]

    assert len(updated.evidence) == 2
    assert updated.root_cause_hypothesis is not None
    assert "bad release" in updated.root_cause_hypothesis


def test_lambda_errors_without_deploy_event_hypothesizes_other_cause() -> None:
    function = _lambda_resource()
    gateway = MockAWSGateway(seed_resources=[function])
    now = datetime.now(timezone.utc)
    gateway.seed_metric_data(
        namespace="AWS/Lambda",
        metric_name="Errors",
        dimensions={"FunctionName": "my-function"},
        datapoints=[{"Timestamp": now.isoformat(), "Sum": 12.0}],
    )
    incident = _incident(IncidentType.LAMBDA_ERRORS, [function])

    node = make_troubleshooting_node(gateway)
    result = node({"incident": incident})
    updated = result["incident"]

    assert updated.root_cause_hypothesis is not None
    assert "no correlated deploy event" in updated.root_cause_hypothesis


def test_lambda_errors_below_threshold_sets_no_hypothesis() -> None:
    function = _lambda_resource()
    gateway = MockAWSGateway(seed_resources=[function])
    incident = _incident(IncidentType.LAMBDA_ERRORS, [function])

    node = make_troubleshooting_node(gateway)
    result = node({"incident": incident})

    assert result["incident"].root_cause_hypothesis is None


def test_no_op_for_unrelated_incident_type() -> None:
    gateway = MockAWSGateway()
    incident = _incident(IncidentType.EC2_HIGH_CPU, [])

    node = make_troubleshooting_node(gateway)
    result = node({"incident": incident})

    assert result["incident"].evidence == []
    assert "no investigation logic" in result["incident"].agent_trace[0].reasoning


def test_no_affected_resource_is_handled_gracefully() -> None:
    gateway = MockAWSGateway()
    incident = _incident(IncidentType.LAMBDA_ERRORS, [])

    node = make_troubleshooting_node(gateway)
    result = node({"incident": incident})

    assert result["incident"].evidence == []
    assert len(result["incident"].agent_trace) == 1
