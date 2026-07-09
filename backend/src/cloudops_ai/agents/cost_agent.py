"""Cost Agent node: investigates billing anomalies.

Honesty note: IReadOnlyAWSTools has no Cost Explorer method yet (see
tools/interfaces.py) -- Cost Explorer's API shape (time-series cost/usage
grouped by dimension) is different enough from the metric/event-shaped
methods already on the interface that it deserves its own method rather
than being force-fit into get_metric_data. Rather than fabricate cost data
or silently do nothing, this node records that fact as its own AgentStep so
the audit trail honestly reflects "we know about this incident type but
can't yet investigate it automatically" instead of looking like a check
that ran and found nothing.
"""

from __future__ import annotations

import uuid
from typing import Callable

from cloudops_ai.agents.state import GraphState
from cloudops_ai.domain.enums import AgentName, IncidentType
from cloudops_ai.domain.models.evidence import AgentStep
from cloudops_ai.tools.interfaces import IReadOnlyAWSTools


def make_cost_node(aws_tools: IReadOnlyAWSTools) -> Callable[[GraphState], GraphState]:
    """Factory that closes over the injected read-only AWS tool set.

    `aws_tools` is accepted (and typed) for interface consistency with
    every other specialist factory, even though this node doesn't call it
    yet -- see the module docstring. Routed to only for HIGH_BILLING
    incidents -- see the routing table in agents/graph.py.
    """

    def cost_node(state: GraphState) -> GraphState:
        incident = state["incident"]
        step = AgentStep(step_id=str(uuid.uuid4()), agent=AgentName.COST, reasoning="")

        if incident.incident_type != IncidentType.HIGH_BILLING:
            step.reasoning = (
                f"Cost Agent has no investigation logic for incident type "
                f"{incident.incident_type.value!r}; nothing to inspect."
            )
        else:
            step.reasoning = (
                "No Cost Explorer adapter exists yet (see tools/interfaces.py) -- this incident cannot "
                "be automatically investigated. Flagging for manual review rather than guessing at a "
                "cause; REMEDIATION_POLICY also has no entry for HIGH_BILLING, by design, so no "
                "automated action would be proposed even if evidence were available."
            )

        step.mark_completed()
        incident.add_agent_step(step)
        return {"incident": incident}

    return cost_node
