"""Monitoring Agent node: reads CloudWatch metrics and decides whether they
represent an anomaly.

Deliberately rule-based, not LLM-backed: "is the average CPU above X%" is a
deterministic comparison, and routing that through an LLM call would make
the system slower, more expensive, and no more correct. The Coordinator
(coordinator.py) is where LLM judgment earns its keep -- deciding *what to
do* about a confirmed anomaly is genuinely ambiguous in a way "is 95 > 90"
is not. The reasoning text attached to the AgentStep is templated from the
actual numbers, not generated, so it is always literally true.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Callable

from cloudops_ai.agents.state import GraphState
from cloudops_ai.domain.enums import AgentName
from cloudops_ai.domain.models.evidence import AgentStep, Evidence
from cloudops_ai.tools.interfaces import IReadOnlyAWSTools

CPU_BREACH_THRESHOLD_PERCENT = 90.0
METRIC_LOOKBACK = timedelta(minutes=15)


def make_monitoring_node(aws_tools: IReadOnlyAWSTools) -> Callable[[GraphState], GraphState]:
    """Factory that closes over the injected read-only AWS tool set."""

    def monitoring_node(state: GraphState) -> GraphState:
        incident = state["incident"]
        step = AgentStep(step_id=str(uuid.uuid4()), agent=AgentName.MONITORING, reasoning="")

        if not incident.affected_resources:
            step.reasoning = "No affected resource on the incident yet; nothing to fetch metrics for."
            step.mark_completed()
            incident.add_agent_step(step)
            return {"incident": incident}

        resource = incident.affected_resources[0]
        instance_id = resource.arn.rsplit("/", 1)[-1]

        end = datetime.now(timezone.utc)
        start = end - METRIC_LOOKBACK
        datapoints = aws_tools.get_metric_data(
            namespace="AWS/EC2",
            metric_name="CPUUtilization",
            dimensions={"InstanceId": instance_id},
            start=start,
            end=end,
        )
        step.tool_calls.append("cloudwatch.get_metric_data")

        averages = [point["Average"] for point in datapoints if "Average" in point]
        mean_cpu = sum(averages) / len(averages) if averages else 0.0
        is_breach = mean_cpu >= CPU_BREACH_THRESHOLD_PERCENT

        evidence = Evidence(
            evidence_id=str(uuid.uuid4()),
            agent=AgentName.MONITORING,
            source="cloudwatch:GetMetricData",
            summary=(
                f"Average CPUUtilization for {instance_id} over the last "
                f"{int(METRIC_LOOKBACK.total_seconds() // 60)} minutes was {mean_cpu:.1f}%"
            ),
            data={"datapoints": datapoints, "mean_cpu_percent": mean_cpu},
        )
        incident.add_evidence(evidence)
        step.evidence_ids.append(evidence.evidence_id)

        step.reasoning = (
            f"Mean CPU over the lookback window is {mean_cpu:.1f}%, which is "
            f"{'at or above' if is_breach else 'below'} the {CPU_BREACH_THRESHOLD_PERCENT:.0f}% "
            f"breach threshold. {'Flagging as an active anomaly.' if is_breach else 'No anomaly detected.'}"
        )
        step.mark_completed()
        incident.add_agent_step(step)

        return {"incident": incident}

    return monitoring_node
