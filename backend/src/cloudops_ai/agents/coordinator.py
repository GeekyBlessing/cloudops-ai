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

A second, related gap found while wiring infra/modules/monitoring's alarms
into this pipeline: infra/modules/eventbridge's CloudWatch-Alarm-state-change
rule is unscoped -- it matches *any* CloudWatch alarm entering ALARM state
in the account, which means this project's own health alarms (ECS CPU/
memory, the incident-triggers DLQ, SQS poller staleness) were already
reaching this pipeline, not "not wired in" as an earlier draft of
infra/README.md claimed. The actual risk was here: asking the LLM to force
one of those alarms into one of the eight customer-resource IncidentType
values below. A plausible LLM guess for "cloudops-ai-dev-ecs-cpu-high" is
EC2_HIGH_CPU, which routes to monitoring_agent.py and calls
`get_metric_data(namespace="AWS/EC2", dimensions={"InstanceId": <this
alarm's own ARN, since it has no "/" for rsplit to find an instance ID
in>})` -- not a crash (CloudWatch's API just returns zero datapoints for a
dimension value that matches nothing), but a plausible-looking *wrong*
investigation result: "checked CPU, found nothing" recorded against an
incident that was never about EC2 CPU at all. `_is_platform_health_alarm`
below short-circuits classification for these deterministically, before the
LLM ever sees them -- the same "the model reasons, code decides" boundary
this file already draws around remediation actions, just drawn one step
earlier here.
"""

from __future__ import annotations

import json
import uuid
from typing import Callable

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage

from cloudops_ai.agents.state import GraphState
from cloudops_ai.domain.enums import AgentName, IncidentType, RemediationStatus, Severity, TriggerSource
from cloudops_ai.domain.models.evidence import AgentStep
from cloudops_ai.domain.models.incident import IncidentState
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

# Alarm-name suffixes for exactly infra/modules/monitoring's four alarms
# ("${var.name_prefix}-ecs-cpu-high", etc.) -- kept in sync with that
# module's `aws_cloudwatch_metric_alarm` resource names *by convention*,
# not by any automated check, same trade-off as GUARDDUTY_SEVERITY_THRESHOLD
# in security_agent.py. Matched as a suffix, not an exact name, because the
# name_prefix varies per environment (e.g. "cloudops-ai-dev" vs a future
# "cloudops-ai-staging") and only the part this project's own Terraform
# controls is stable.
_PLATFORM_ALARM_NAME_SUFFIXES: dict[str, Severity] = {
    # The two SQS alarms are HIGH, not MEDIUM: they mean the incident
    # *intake* pipeline itself may be broken, which threatens this
    # system's ability to detect and report every other incident, not
    # just this one.
    "-incident-triggers-dlq-depth": Severity.HIGH,
    "-incident-triggers-oldest-message-age": Severity.HIGH,
    "-ecs-cpu-high": Severity.MEDIUM,
    "-ecs-memory-high": Severity.MEDIUM,
}


def _platform_health_alarm_severity(incident: IncidentState) -> Severity | None:
    """Returns a severity if this incident is one of this project's own
    monitoring alarms (infra/modules/monitoring), or None if it isn't --
    None means "let the LLM classify this normally," not "not severe."

    Deliberately checks the alarm's *name* (CloudWatch's own identifier for
    it), not resource_type alone -- a GuardDuty finding or a genuine
    customer CloudWatch alarm on an EC2 instance both need normal LLM
    classification, and resource_type alone can't tell those apart from
    this project's own alarms the way the name suffix can.
    """
    if incident.trigger_source != TriggerSource.CLOUDWATCH_ALARM:
        return None
    if not incident.affected_resources:
        return None
    resource = incident.affected_resources[0]
    if resource.resource_type != "AWS::CloudWatch::Alarm" or not resource.name:
        return None
    for suffix, severity in _PLATFORM_ALARM_NAME_SUFFIXES.items():
        if resource.name.endswith(suffix):
            return severity
    return None


def make_classify_node(chat_model: BaseChatModel) -> Callable[[GraphState], GraphState]:
    """Factory for the classification node -- the first thing that runs for
    any new incident.
    """

    def classify_node(state: GraphState) -> GraphState:
        incident = state["incident"]
        step = AgentStep(step_id=str(uuid.uuid4()), agent=AgentName.COORDINATOR, reasoning="")

        # Deterministic short-circuit, checked before any LLM call: one of
        # this project's own monitoring alarms (infra/modules/monitoring)
        # never needs the LLM to guess what kind of incident it is -- we
        # already know, by construction, from which alarm fired. See this
        # module's docstring and _platform_health_alarm_severity's for why
        # this has to be deterministic rather than trusting the LLM to
        # recognize "this isn't a customer resource" reliably.
        platform_severity = _platform_health_alarm_severity(incident)
        if platform_severity is not None:
            alarm_name = incident.affected_resources[0].name
            incident.incident_type = IncidentType.PLATFORM_HEALTH_ALARM
            incident.severity = platform_severity
            step.reasoning = (
                f"Recognized '{alarm_name}' as one of this project's own monitoring alarms "
                f"(infra/modules/monitoring) by name convention -- classified as "
                f"{IncidentType.PLATFORM_HEALTH_ALARM.value}/{platform_severity.value} without an LLM call. "
                "No specialist agent runs for this incident type (see graph.py's routing table) and no "
                "remediation action can be proposed (absent from REMEDIATION_POLICY) -- this is a report-only "
                "record that the platform itself needs attention, not something to investigate with tools "
                "built for customer AWS resources."
            )
            step.mark_completed()
            incident.add_agent_step(step)
            return {"incident": incident}

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
            # Bug fixed here: plan.status defaults to NOT_STARTED and was
            # previously left at that default while only incident.remediation_status
            # was updated below -- the two fields drifted out of sync, and the
            # /remediation router's approval check (which reads plan.status,
            # correctly, since the plan is the thing being approved) always
            # saw NOT_STARTED and rejected every approval with a 409. Caught
            # by tests/unit/api/test_remediation_router.py once that router
            # actually existed to expose it.
            status=plan_status,
        )
        incident.proposed_remediation = plan
        incident.remediation_status = plan_status

        step.reasoning = f"Proposed action '{action_name}' on {target.arn}: {rationale}"
        step.mark_completed()
        incident.add_agent_step(step)

        return {"incident": incident}

    return decide_node
