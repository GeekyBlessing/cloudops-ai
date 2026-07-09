"""Infrastructure Agent node: checks EC2 instance state for down-instance
incidents, and RDS free storage for storage-full incidents.
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
RDS_FREE_STORAGE_THRESHOLD_BYTES = 2_000_000_000  # 2 GB -- below this, treat as "storage full" territory
_DOWN_STATES = {"stopped", "stopping", "terminated", "shutting-down"}


def make_infrastructure_node(aws_tools: IReadOnlyAWSTools) -> Callable[[GraphState], GraphState]:
    """Factory that closes over the injected read-only AWS tool set.

    Routed to only for EC2_DOWN and RDS_STORAGE_FULL incidents -- see the
    routing table in agents/graph.py.
    """

    def infrastructure_node(state: GraphState) -> GraphState:
        incident = state["incident"]
        step = AgentStep(step_id=str(uuid.uuid4()), agent=AgentName.INFRASTRUCTURE, reasoning="")

        if not incident.affected_resources:
            step.reasoning = "No affected resource on the incident yet; nothing to inspect."
            step.mark_completed()
            incident.add_agent_step(step)
            return {"incident": incident}

        resource = incident.affected_resources[0]

        if incident.incident_type == IncidentType.EC2_DOWN:
            instance_id = resource.arn.rsplit("/", 1)[-1]
            described = aws_tools.describe_instance(instance_id)
            step.tool_calls.append("ec2.describe_instance")

            instance_state = str(described.attributes.get("state", "unknown"))
            is_down = instance_state in _DOWN_STATES

            evidence = Evidence(
                evidence_id=str(uuid.uuid4()),
                agent=AgentName.INFRASTRUCTURE,
                source="ec2:DescribeInstances",
                summary=f"Instance {instance_id} reports state {instance_state!r}",
                data={"instance_id": instance_id, "state": instance_state},
            )
            incident.add_evidence(evidence)
            step.evidence_ids.append(evidence.evidence_id)
            step.reasoning = (
                f"Instance {instance_id} is in state {instance_state!r}, which "
                f"{'confirms' if is_down else 'does not confirm'} the instance is down."
            )

        elif incident.incident_type == IncidentType.RDS_STORAGE_FULL:
            db_instance_id = resource.arn.rsplit(":", 1)[-1]
            end = datetime.now(timezone.utc)
            start = end - METRIC_LOOKBACK
            datapoints = aws_tools.get_metric_data(
                namespace="AWS/RDS",
                metric_name="FreeStorageSpace",
                dimensions={"DBInstanceIdentifier": db_instance_id},
                start=start,
                end=end,
            )
            step.tool_calls.append("cloudwatch.get_metric_data")

            averages = [point["Average"] for point in datapoints if "Average" in point]
            mean_free_bytes = sum(averages) / len(averages) if averages else 0.0
            is_low = mean_free_bytes <= RDS_FREE_STORAGE_THRESHOLD_BYTES

            evidence = Evidence(
                evidence_id=str(uuid.uuid4()),
                agent=AgentName.INFRASTRUCTURE,
                source="cloudwatch:GetMetricData",
                summary=(
                    f"Average FreeStorageSpace for {db_instance_id} over the last "
                    f"{int(METRIC_LOOKBACK.total_seconds() // 60)} minutes was {mean_free_bytes / 1e9:.2f} GB"
                ),
                data={"datapoints": datapoints, "mean_free_bytes": mean_free_bytes},
            )
            incident.add_evidence(evidence)
            step.evidence_ids.append(evidence.evidence_id)
            step.reasoning = (
                f"Mean free storage is {mean_free_bytes / 1e9:.2f} GB, which is "
                f"{'at or below' if is_low else 'above'} the {RDS_FREE_STORAGE_THRESHOLD_BYTES / 1e9:.0f} GB "
                f"threshold. {'Flagging as low storage.' if is_low else 'No anomaly detected.'}"
            )

        else:
            step.reasoning = (
                f"Infrastructure Agent has no investigation logic for incident type "
                f"{incident.incident_type.value!r}; nothing to inspect."
            )

        step.mark_completed()
        incident.add_agent_step(step)
        return {"incident": incident}

    return infrastructure_node
