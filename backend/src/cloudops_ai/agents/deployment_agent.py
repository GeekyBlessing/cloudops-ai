"""Deployment Agent node: correlates Auto Scaling failures with recent
configuration-changing CloudTrail events on the same Auto Scaling Group,
to answer "did a recent change cause this?"
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Callable

from cloudops_ai.agents.state import GraphState
from cloudops_ai.domain.enums import AgentName, IncidentType
from cloudops_ai.domain.models.evidence import AgentStep, Evidence
from cloudops_ai.tools.interfaces import IReadOnlyAWSTools

LOOKBACK = timedelta(hours=1)
_CONFIG_CHANGE_EVENT_NAMES = {
    "UpdateAutoScalingGroup",
    "CreateLaunchConfiguration",
    "CreateOrUpdateTags",
    "PutScalingPolicy",
}


def make_deployment_node(aws_tools: IReadOnlyAWSTools) -> Callable[[GraphState], GraphState]:
    """Factory that closes over the injected read-only AWS tool set.

    Routed to only for AUTO_SCALING_FAILURE incidents -- see the routing
    table in agents/graph.py. A wider lookback window (1 hour, vs. 15
    minutes for Monitoring/Troubleshooting) is used deliberately: a bad
    Auto Scaling Group config change is often the root cause of a failure
    that only manifests once a scaling event actually triggers, which can
    lag the change by longer than the tighter windows used elsewhere.
    """

    def deployment_node(state: GraphState) -> GraphState:
        incident = state["incident"]
        step = AgentStep(step_id=str(uuid.uuid4()), agent=AgentName.DEPLOYMENT, reasoning="")

        if incident.incident_type != IncidentType.AUTO_SCALING_FAILURE:
            step.reasoning = (
                f"Deployment Agent has no investigation logic for incident type "
                f"{incident.incident_type.value!r}; nothing to inspect."
            )
            step.mark_completed()
            incident.add_agent_step(step)
            return {"incident": incident}

        if not incident.affected_resources:
            step.reasoning = "No affected resource on the incident yet; nothing to correlate."
            step.mark_completed()
            incident.add_agent_step(step)
            return {"incident": incident}

        resource = incident.affected_resources[0]
        end = datetime.now(timezone.utc)
        start = end - LOOKBACK

        events = aws_tools.lookup_cloudtrail_events(resource_arn=resource.arn, start=start, end=end)
        step.tool_calls.append("cloudtrail.lookup_events")
        config_change_events = [event for event in events if event.get("EventName") in _CONFIG_CHANGE_EVENT_NAMES]

        evidence = Evidence(
            evidence_id=str(uuid.uuid4()),
            agent=AgentName.DEPLOYMENT,
            source="cloudtrail:LookupEvents",
            summary=(
                f"Found {len(config_change_events)} configuration-changing CloudTrail event(s) for "
                f"{resource.name or resource.arn} in the last {int(LOOKBACK.total_seconds() // 3600)} hour(s)"
            ),
            data={"config_change_events": config_change_events},
        )
        incident.add_evidence(evidence)
        step.evidence_ids.append(evidence.evidence_id)

        if config_change_events:
            incident.root_cause_hypothesis = (
                f"Auto Scaling Group {resource.name or resource.arn} had {len(config_change_events)} "
                "configuration change(s) shortly before this failure -- likely cause is a bad config "
                "change rather than pure capacity exhaustion."
            )
        step.reasoning = (
            f"{len(config_change_events)} configuration-changing event(s) found in the lookback window. "
            f"{incident.root_cause_hypothesis or 'No recent configuration changes correlate with this failure.'}"
        )
        step.mark_completed()
        incident.add_agent_step(step)
        return {"incident": incident}

    return deployment_node
