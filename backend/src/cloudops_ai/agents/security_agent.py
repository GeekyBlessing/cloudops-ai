"""Security Agent node: investigates S3 public-access exposure and IAM/
GuardDuty security findings.

Like Monitoring, this is rule-based rather than LLM-backed for the same
reason: "is this bucket public" and "did GuardDuty raise a finding at or
above this severity" are deterministic API answers, not judgment calls. The
Coordinator's decide_node is still the only place that turns a security
finding into a proposed action.
"""

from __future__ import annotations

import uuid
from typing import Callable

from cloudops_ai.agents.state import GraphState
from cloudops_ai.domain.enums import AgentName, IncidentType
from cloudops_ai.domain.models.evidence import AgentStep, Evidence
from cloudops_ai.tools.interfaces import IReadOnlyAWSTools

GUARDDUTY_SEVERITY_THRESHOLD = 4.0


def _extract_bucket_name(arn: str) -> str:
    """`arn:aws:s3:::bucket-name` -> `bucket-name` (S3 bucket ARNs carry no region/account segment)."""
    return arn.split(":::", 1)[-1]


def make_security_node(aws_tools: IReadOnlyAWSTools) -> Callable[[GraphState], GraphState]:
    """Factory that closes over the injected read-only AWS tool set.

    Routed to only for PUBLIC_S3_BUCKET and IAM_MISCONFIGURATION incidents
    -- see the routing table in agents/graph.py.
    """

    def security_node(state: GraphState) -> GraphState:
        incident = state["incident"]
        step = AgentStep(step_id=str(uuid.uuid4()), agent=AgentName.SECURITY, reasoning="")

        if incident.incident_type == IncidentType.PUBLIC_S3_BUCKET:
            if not incident.affected_resources:
                step.reasoning = "No affected resource on the incident yet; nothing to check for public access."
                step.mark_completed()
                incident.add_agent_step(step)
                return {"incident": incident}

            resource = incident.affected_resources[0]
            bucket_name = _extract_bucket_name(resource.arn)
            is_public = aws_tools.get_bucket_public_access(bucket_name)
            step.tool_calls.append("s3.get_bucket_public_access")

            evidence = Evidence(
                evidence_id=str(uuid.uuid4()),
                agent=AgentName.SECURITY,
                source="s3:GetBucketPublicAccessBlock",
                summary=f"Bucket {bucket_name} public access check: {'PUBLIC' if is_public else 'not public'}",
                data={"bucket_name": bucket_name, "is_public": is_public},
            )
            incident.add_evidence(evidence)
            step.evidence_ids.append(evidence.evidence_id)
            step.reasoning = (
                f"Bucket {bucket_name} "
                f"{'grants public access and requires remediation' if is_public else 'does not grant public access -- likely a stale or resolved alert'}."
            )

        elif incident.incident_type == IncidentType.IAM_MISCONFIGURATION:
            findings = aws_tools.get_guardduty_findings(severity_threshold=GUARDDUTY_SEVERITY_THRESHOLD)
            step.tool_calls.append("guardduty.get_guardduty_findings")

            evidence = Evidence(
                evidence_id=str(uuid.uuid4()),
                agent=AgentName.SECURITY,
                source="guardduty:ListFindings",
                summary=(
                    f"GuardDuty returned {len(findings)} active finding(s) at or above severity "
                    f"{GUARDDUTY_SEVERITY_THRESHOLD}"
                ),
                data={"findings": findings, "severity_threshold": GUARDDUTY_SEVERITY_THRESHOLD},
            )
            incident.add_evidence(evidence)
            step.evidence_ids.append(evidence.evidence_id)
            step.reasoning = (
                f"{len(findings)} GuardDuty finding(s) at or above severity {GUARDDUTY_SEVERITY_THRESHOLD} "
                f"{'support flagging this as an active IAM misconfiguration' if findings else 'were found -- this may be a false positive or already-resolved alert'}."
            )

        else:
            step.reasoning = (
                f"Security Agent has no investigation logic for incident type "
                f"{incident.incident_type.value!r}; nothing to check."
            )

        step.mark_completed()
        incident.add_agent_step(step)
        return {"incident": incident}

    return security_node
