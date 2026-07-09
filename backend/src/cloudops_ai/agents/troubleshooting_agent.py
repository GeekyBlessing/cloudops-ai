"""Troubleshooting Agent node: investigates Lambda error spikes by
correlating CloudWatch error-count metrics with recent CloudTrail deploy
events for the same function.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Callable

from cloudops_ai.agents.state import GraphState
from cloudops_ai.domain.enums import AgentName, IncidentType
from cloudops_ai.domain.models.evidence import AgentStep, Evidence
from cloudops_ai.tools.interfaces import IReadOnlyAWSTools

METRIC_LOOKBACK = timedelta(minutes=15)
LAMBDA_ERROR_COUNT_THRESHOLD = 5.0
_DEPLOY_EVENT_NAMES = {"UpdateFunctionCode20150331v2", "UpdateFunctionCode", "PublishVersion"}


def make_troubleshooting_node(aws_tools: IReadOnlyAWSTools) -> Callable[[GraphState], GraphState]:
    """Factory that closes over the injected read-only AWS tool set.

    Routed to only for LAMBDA_ERRORS incidents -- see the routing table in
    agents/graph.py.
    """

    def troubleshooting_node(state: GraphState) -> GraphState:
        incident = state["incident"]
        step = AgentStep(step_id=str(uuid.uuid4()), agent=AgentName.TROUBLESHOOTING, reasoning="")

        if incident.incident_type != IncidentType.LAMBDA_ERRORS:
            step.reasoning = (
                f"Troubleshooting Agent has no investigation logic for incident type "
                f"{incident.incident_type.value!r}; nothing to inspect."
            )
            step.mark_completed()
            incident.add_agent_step(step)
            return {"incident": incident}

        if not incident.affected_resources:
            step.reasoning = "No affected resource on the incident yet; nothing to inspect."
            step.mark_completed()
            incident.add_agent_step(step)
            return {"incident": incident}

        resource = incident.affected_resources[0]
        function_name = resource.arn.rsplit(":", 1)[-1]
        end = datetime.now(timezone.utc)
        start = end - METRIC_LOOKBACK

        datapoints = aws_tools.get_metric_data(
            namespace="AWS/Lambda",
            metric_name="Errors",
            dimensions={"FunctionName": function_name},
            start=start,
            end=end,
        )
        step.tool_calls.append("cloudwatch.get_metric_data")

        totals = [point.get("Sum", point.get("Average", 0.0)) for point in datapoints]
        error_count = sum(totals)

        events = aws_tools.lookup_cloudtrail_events(resource_arn=resource.arn, start=start, end=end)
        step.tool_calls.append("cloudtrail.lookup_events")
        deploy_events = [event for event in events if event.get("EventName") in _DEPLOY_EVENT_NAMES]

        metric_evidence = Evidence(
            evidence_id=str(uuid.uuid4()),
            agent=AgentName.TROUBLESHOOTING,
            source="cloudwatch:GetMetricData",
            summary=(
                f"Function {function_name} recorded {error_count:.0f} error(s) over the last "
                f"{int(METRIC_LOOKBACK.total_seconds() // 60)} minutes"
            ),
            data={"datapoints": datapoints, "error_count": error_count},
        )
        incident.add_evidence(metric_evidence)
        step.evidence_ids.append(metric_evidence.evidence_id)

        cloudtrail_evidence = Evidence(
            evidence_id=str(uuid.uuid4()),
            agent=AgentName.TROUBLESHOOTING,
            source="cloudtrail:LookupEvents",
            summary=(
                f"Found {len(deploy_events)} deploy-related CloudTrail event(s) for {function_name} "
                "in the lookback window"
            ),
            data={"deploy_events": deploy_events},
        )
        incident.add_evidence(cloudtrail_evidence)
        step.evidence_ids.append(cloudtrail_evidence.evidence_id)

        is_breach = error_count >= LAMBDA_ERROR_COUNT_THRESHOLD
        if is_breach and deploy_events:
            incident.root_cause_hypothesis = (
                f"{function_name} began erroring shortly after a code deployment "
                f"({len(deploy_events)} deploy event(s) in the lookback window) -- likely a bad release."
            )
        elif is_breach:
            incident.root_cause_hypothesis = (
                f"{function_name} is erroring ({error_count:.0f} errors) with no correlated deploy event -- "
                "likely a dependency, permissions, or downstream service issue rather than a bad release."
            )

        step.reasoning = (
            f"{error_count:.0f} error(s) recorded ({'at or above' if is_breach else 'below'} the "
            f"{LAMBDA_ERROR_COUNT_THRESHOLD:.0f}-error threshold), with {len(deploy_events)} correlated deploy "
            f"event(s). {incident.root_cause_hypothesis or 'No anomaly detected.'}"
        )
        step.mark_completed()
        incident.add_agent_step(step)
        return {"incident": incident}

    return troubleshooting_node
