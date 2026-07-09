"""Unit tests for the Deployment Agent node."""

from __future__ import annotations

from datetime import datetime, timezone

from cloudops_ai.adapters.mock.mock_aws_gateway import MockAWSGateway
from cloudops_ai.agents.deployment_agent import make_deployment_node
from cloudops_ai.domain.enums import IncidentType, TriggerSource
from cloudops_ai.domain.models.incident import IncidentState
from cloudops_ai.domain.models.resource import ResourceRef


def _asg_resource() -> ResourceRef:
    return ResourceRef(
        arn="arn:aws:autoscaling:us-east-1:123456789012:autoScalingGroup:abc123:autoScalingGroupName/my-asg",
        resource_type="AWS::AutoScaling::AutoScalingGroup",
        region="us-east-1",
        account_id="123456789012",
        name="my-asg",
    )


def _incident(incident_type: IncidentType, resources: list[ResourceRef]) -> IncidentState:
    return IncidentState(
        incident_id="incident-1",
        trigger_source=TriggerSource.CLOUDWATCH_ALARM,
        affected_resources=resources,
        incident_type=incident_type,
    )


def test_auto_scaling_failure_with_recent_config_change_hypothesizes_bad_config() -> None:
    asg = _asg_resource()
    gateway = MockAWSGateway(seed_resources=[asg])
    now = datetime.now(timezone.utc)
    gateway.seed_cloudtrail_events(
        asg.arn,
        [{"EventName": "UpdateAutoScalingGroup", "EventTime": now.isoformat()}],
    )
    incident = _incident(IncidentType.AUTO_SCALING_FAILURE, [asg])

    node = make_deployment_node(gateway)
    result = node({"incident": incident})
    updated = result["incident"]

    assert len(updated.evidence) == 1
    assert updated.root_cause_hypothesis is not None
    assert "bad config change" in updated.root_cause_hypothesis


def test_auto_scaling_failure_without_config_change_sets_no_hypothesis() -> None:
    asg = _asg_resource()
    gateway = MockAWSGateway(seed_resources=[asg])
    incident = _incident(IncidentType.AUTO_SCALING_FAILURE, [asg])

    node = make_deployment_node(gateway)
    result = node({"incident": incident})

    assert result["incident"].root_cause_hypothesis is None


def test_no_op_for_unrelated_incident_type() -> None:
    gateway = MockAWSGateway()
    incident = _incident(IncidentType.EC2_HIGH_CPU, [])

    node = make_deployment_node(gateway)
    result = node({"incident": incident})

    assert result["incident"].evidence == []
    assert "no investigation logic" in result["incident"].agent_trace[0].reasoning


def test_no_affected_resource_is_handled_gracefully() -> None:
    gateway = MockAWSGateway()
    incident = _incident(IncidentType.AUTO_SCALING_FAILURE, [])

    node = make_deployment_node(gateway)
    result = node({"incident": incident})

    assert result["incident"].evidence == []
    assert len(result["incident"].agent_trace) == 1
