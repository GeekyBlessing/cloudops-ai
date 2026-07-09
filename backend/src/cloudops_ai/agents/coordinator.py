"""Coordinator Agent: classifies incoming incidents and, after specialists
have gathered evidence, decides on (and gates) a remediation plan.

The Coordinator is the one node in this skeleton that calls an LLM --
classification ("what kind of incident is this?") and remediation rationale
are genuinely judgment calls in a way a metric threshold isn't. Even so,
the LLM's output is deliberately constrained on both ends:

* Classification output is parsed against the IncidentType/Severity enums --
  a response that doesn't match a known enum value is rejected outright,
  not silently accepted as some new category the rest of the system has
  never heard of.
* The LLM is NEVER asked to choose the remediation *action*. The action
  always comes from the deterministic policy table
  (domain/policies/remediation_policy.py). The LLM only ever supplies the
  human-readable rationale text that goes into the report. This mirrors
  /docs/ARCHITECTURE.md section 7: the model can reason freely, but it
  cannot act outside an allow-list -- there is no code path from "LLM
  output" to "AWS mutation" that skips the policy table.

`chat_model` is typed as LangChain's `BaseChatModel`, which is what makes
this provider-agnostic: Claude, GPT-4o, or a local model all satisfy this
interface, and a `FakeListChatModel` satisfies it too, which is how
tests/unit/agents/test_graph.py exercises this file without calling a real
LLM API.

Bug fixed alongside the EventBridge/SQS trigger pipeline: classify_node's
prompt used to be built from `incident.model_dump_json(include={"incident_id",
"trigger_source"})` -- literally just an ID and an enum value, nothing about
*what actually happened*. That was invisible while the only trigger path was
the manual API endpoint (which itself barely carries more than an instance
ARN), but it meant a real CloudWatch Alarm or GuardDuty Finding delivered via
SQS would get classified blind, since none of the alarm/finding detail ever
reached the LLM. The prompt now also includes `affected_resources` and
`raw_trigger_payload`, so classification has the actual alarm name, finding
type, severity, etc. to work with.
"""

from __future__ import annotations

import json
import uuid
from typing import Callable

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage

from cloudops_ai.agents.state import GraphState
from cloudops_ai.domain.enums import AgentName, IncidentType, RemediationStatus, Severity
from cloudops_ai.domain.models.evidence import AgentStep
from cloudops_ai.domain.models.remediation import RemediationAction, RemediationPlan
from cloudops_ai.domain.policies.remediation_policy import REMEDIATION_POLICY

_CLASSIFY_PROMPT = """You are the Coordinator agent in an AWS incident response system.
Given the raw trigger payload below, classify the incident.

Respond with ONLY a JSON object of the form:
{{"incident_type": "<one of: ec2_high_cpu, ec2_down, public_s3_bucket, iam_misconfiguration, \
high_billing, lambda_errors, rds_storage_full, auto_scaling_failure, unknown>", \
"severity": "<one of: low, medium, high, critical>"}}

Trigger payload:
{payload}
"""


def make_classify_node(chat_model: BaseChatModel) -> Callable[[GraphState], GraphState]:
    """Factory for the classification node -- the first thing that runs for
    any new incident.
    """

    def classify_node(state: GraphState) -> GraphState:
        incident = state["incident"]
        step = AgentStep(step_id=str(uuid.uuid4()), agent=AgentName.COORDINATOR, reasoning="")

        payload = incident.model_dump_json(
            include={"incident_id", "trigger_source", "affected_resources", "raw_trigger_payload"}
        )
        prompt = _CLASSIFY_PROMPT.format(payload=payload)
        response = chat_model.invoke([HumanMessage(content=prompt)])
        step.tool_calls.append("llm.classify")

        try:
            parsed = json.loads(str(response.content))
            incident_type = IncidentType(parsed["incident_type"])
            severity = Severity(parsed["severity"])
        except (json.JSONDecodeError, KeyError, ValueError) as exc:
            # Fail safe: an unparseable or unrecognized classification leaves
            # the incident UNKNOWN rather than crashing the graph or guessing.
            step.reasoning = f"Could not parse a valid classification from the model ({exc}); leaving as UNKNOWN."
            step.mark_completed()
            incident.add_agent_step(step)
            return {"incident": incident}

        incident.incident_type = incident_type
        incident.severity = severity
        step.reasoning = f"Classified as {incident_type.value} / {severity.value} severity."
        step.mark_completed()
        incident.add_agent_step(step)

        return {"incident": incident}

    return classify_node


_RATIONALE_PROMPT = """You are the Coordinator agent. Based on the evidence below, write a
2-3 sentence rationale for taking the action "{action_name}" on {target_arn}.
Be specific about what the evidence shows. Do not suggest any other action.

Evidence:
{evidence_summaries}
"""


def make_decide_node(chat_model: BaseChatModel) -> Callable[[GraphState], GraphState]:
    """Factory for the decide node -- runs after specialists have gathered
    evidence, and produces (or explicitly declines to produce) a
    RemediationPlan.
    """

    def decide_node(state: GraphState) -> GraphState:
        incident = state["incident"]
        step = AgentStep(step_id=str(uuid.uuid4()), agent=AgentName.COORDINATOR, reasoning="")

        if incident.severity is None:
            step.reasoning = "No severity set (classification failed upstream); skipping remediation planning."
            step.mark_completed()
            incident.add_agent_step(step)
            return {"incident": incident}

        policy_entry = REMEDIATION_POLICY.get((incident.incident_type, incident.severity))
        if policy_entry is None or not incident.affected_resources:
            step.reasoning = (
                f"No remediation policy entry for {incident.incident_type.value}/{incident.severity.value} "
                "(or no affected resource identified) -- the report will carry a recommendation only, "
                "with no automated action proposed."
            )
            step.mark_completed()
            incident.add_agent_step(step)
            return {"incident": incident}

        # Deterministic choice: the LLM never picks the action, only explains it.
        # `sorted()` makes the pick reproducible across runs given the same policy entry.
        action_name = sorted(policy_entry.allowed_actions)[0]
        target = incident.affected_resources[0]

        evidence_summaries = "\n".join(f"- {item.summary}" for item in incident.evidence) or "(no evidence collected)"
        prompt = _RATIONALE_PROMPT.format(
            action_name=action_name, target_arn=target.arn, evidence_summaries=evidence_summaries
        )
        response = chat_model.invoke([HumanMessage(content=prompt)])
        rationale = str(response.content).strip()
        step.tool_calls.append("llm.rationale")

        plan_status = (
            RemediationStatus.AWAITING_APPROVAL if policy_entry.requires_approval else RemediationStatus.NOT_STARTED
        )
        plan = RemediationPlan(
            plan_id=str(uuid.uuid4()),
            incident_id=incident.incident_id,
            actions=[
                RemediationAction(action_name=action_name, target_arn=target.arn, is_reversible=True),
            ],
            requires_approval=policy_entry.requires_approval,
            rationale=rationale,
            status=plan_status,
        )
        incident.proposed_remediation = plan
        incident.remediation_status = plan_status

        step.reasoning = f"Proposed action '{action_name}' on {target.arn}: {rationale}"
        step.mark_completed()
        incident.add_agent_step(step)

        return {"incident": incident}

    return decide_node
