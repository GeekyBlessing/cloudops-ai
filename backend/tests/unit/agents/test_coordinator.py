"""Unit tests for the Coordinator's classify_node -- specifically the
classification prompt payload, not the LLM's response handling (test_graph.py
already covers end-to-end classification with a FakeListChatModel).

The first two tests exist because of a real bug found while building the
EventBridge/SQS trigger pipeline: classify_node used to build its prompt
from only `incident_id` and `trigger_source`, so a real CloudWatch Alarm or
GuardDuty Finding delivered via SQS would be classified blind -- none of
the alarm/finding detail ever reached the LLM. See coordinator.py's
docstring for the full explanation.

The platform-health-alarm tests below exist because of a related, later
finding: infra/modules/eventbridge's CloudWatch-Alarm-state-change rule is
unscoped, so this project's own monitoring alarms (infra/modules/monitoring)
already reached this pipeline -- and without the deterministic short-circuit
these tests cover, they'd have been handed to the LLM to force-fit into an
IncidentType meant for customer AWS resources. See coordinator.py's
docstring and _platform_health_alarm_severity for the full explanation.
"""

from __future__ import annotations

from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from cloudops_ai.agents.coordinator import make_classify_node
from cloudops_ai.agents.state import build_initial_state
from cloudops_ai.domain.enums import IncidentType, Severity, TriggerSource
from cloudops_ai.domain.models.incident import IncidentState
from cloudops_ai.domain.models.resource import ResourceRef


class _SpyChatModel(BaseChatModel):
    """Records every prompt it's invoked with, so tests can assert on
    exactly what the Coordinator sent to the LLM -- FakeListChatModel
    (used everywhere else in this test suite) returns scripted responses
    but doesn't expose what it was called with.
    """

    response_content: str = '{"incident_type": "unknown", "severity": "low"}'
    received_messages: list[list[BaseMessage]] = []

    def __init__(self, **data: Any) -> None:
        super().__init__(**data)
        object.__setattr__(self, "received_messages", [])

    @property
    def _llm_type(self) -> str:
        return "spy"

    def _generate(self, messages: list[BaseMessage], stop=None, run_manager=None, **kwargs: Any) -> ChatResult:
        self.received_messages.append(messages)
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=self.response_content))])


def test_classification_prompt_includes_affected_resources_and_raw_trigger_payload() -> None:
    resource = ResourceRef(
        arn="arn:aws:ec2:us-east-1:123456789012:instance/i-0abcd1234",
        resource_type="AWS::EC2::Instance",
        region="us-east-1",
        account_id="123456789012",
    )
    incident = IncidentState(
        incident_id="incident-1",
        trigger_source=TriggerSource.CLOUDWATCH_ALARM,
        affected_resources=[resource],
        raw_trigger_payload={"detail-type": "CloudWatch Alarm State Change", "detail": {"alarmName": "high-cpu"}},
    )

    spy = _SpyChatModel()
    classify_node = make_classify_node(spy)
    classify_node(build_initial_state(incident))

    assert len(spy.received_messages) == 1
    prompt_text = spy.received_messages[0][0].content

    # The bug this test guards against: these two fields used to be
    # entirely absent from the prompt.
    assert "i-0abcd1234" in prompt_text
    assert "high-cpu" in prompt_text


def test_classification_prompt_omits_resources_field_when_none_present() -> None:
    """A MANUAL incident (the existing dashboard "New incident" form) has
    no raw_trigger_payload and its own affected_resources -- this just
    confirms the field additions don't break the case that already worked.
    """
    incident = IncidentState(incident_id="incident-2", trigger_source=TriggerSource.MANUAL)

    spy = _SpyChatModel()
    classify_node = make_classify_node(spy)
    result = classify_node(build_initial_state(incident))

    assert len(spy.received_messages) == 1
    assert result["incident"].agent_trace[-1].tool_calls == ["llm.classify"]


def test_platform_health_alarm_classified_without_calling_llm() -> None:
    """The deterministic short-circuit this test guards: an incident whose
    resource is one of infra/modules/monitoring's own alarms must never
    reach the LLM at all -- not just get correctly classified by it.
    """
    resource = ResourceRef(
        arn="arn:aws:cloudwatch:us-east-1:123456789012:alarm:cloudops-ai-dev-incident-triggers-dlq-depth",
        resource_type="AWS::CloudWatch::Alarm",
        region="us-east-1",
        account_id="123456789012",
        name="cloudops-ai-dev-incident-triggers-dlq-depth",
    )
    incident = IncidentState(
        incident_id="incident-3",
        trigger_source=TriggerSource.CLOUDWATCH_ALARM,
        affected_resources=[resource],
        raw_trigger_payload={"detail-type": "CloudWatch Alarm State Change"},
    )

    spy = _SpyChatModel()
    classify_node = make_classify_node(spy)
    result = classify_node(build_initial_state(incident))

    assert spy.received_messages == []  # The LLM must never be invoked for this case.
    updated = result["incident"]
    assert updated.incident_type == IncidentType.PLATFORM_HEALTH_ALARM
    assert updated.severity == Severity.HIGH  # DLQ depth -- see _PLATFORM_ALARM_NAME_SUFFIXES.
    assert updated.agent_trace[-1].tool_calls == []


def test_platform_health_alarm_ecs_cpu_gets_medium_severity() -> None:
    resource = ResourceRef(
        arn="arn:aws:cloudwatch:us-east-1:123456789012:alarm:cloudops-ai-dev-ecs-cpu-high",
        resource_type="AWS::CloudWatch::Alarm",
        region="us-east-1",
        account_id="123456789012",
        name="cloudops-ai-dev-ecs-cpu-high",
    )
    incident = IncidentState(
        incident_id="incident-4",
        trigger_source=TriggerSource.CLOUDWATCH_ALARM,
        affected_resources=[resource],
    )

    spy = _SpyChatModel()
    classify_node = make_classify_node(spy)
    result = classify_node(build_initial_state(incident))

    assert spy.received_messages == []
    assert result["incident"].incident_type == IncidentType.PLATFORM_HEALTH_ALARM
    assert result["incident"].severity == Severity.MEDIUM


def test_customer_cloudwatch_alarm_still_goes_through_the_llm() -> None:
    """The counterpart to the platform-alarm tests above: a real customer
    EC2 alarm (a CloudWatch::Alarm resource whose name doesn't match one of
    this project's own alarm suffixes) must still be classified normally --
    the short-circuit is name-scoped, not resource-type-scoped.
    """
    resource = ResourceRef(
        arn="arn:aws:cloudwatch:us-east-1:123456789012:alarm:customer-prod-high-cpu",
        resource_type="AWS::CloudWatch::Alarm",
        region="us-east-1",
        account_id="123456789012",
        name="customer-prod-high-cpu",
    )
    incident = IncidentState(
        incident_id="incident-5",
        trigger_source=TriggerSource.CLOUDWATCH_ALARM,
        affected_resources=[resource],
    )

    spy = _SpyChatModel(response_content='{"incident_type": "ec2_high_cpu", "severity": "high"}')
    classify_node = make_classify_node(spy)
    result = classify_node(build_initial_state(incident))

    assert len(spy.received_messages) == 1
    assert result["incident"].incident_type == IncidentType.EC2_HIGH_CPU


def test_cloudwatch_alarm_incident_with_no_affected_resources_goes_through_the_llm() -> None:
    """A CLOUDWATCH_ALARM-triggered incident that (for whatever reason)
    carries no affected_resources yet can't be checked against the
    platform-alarm name suffixes. _platform_health_alarm_severity must
    return None here -- not crash on an empty list index -- and let normal
    LLM classification proceed, exactly like the MANUAL case above.
    """
    incident = IncidentState(incident_id="incident-6", trigger_source=TriggerSource.CLOUDWATCH_ALARM)
    assert incident.affected_resources == []
    spy = _SpyChatModel(response_content='{"incident_type": "unknown", "severity": "low"}')
    classify_node = make_classify_node(spy)
    result = classify_node(build_initial_state(incident))
    assert len(spy.received_messages) == 1
    assert result["incident"].incident_type == IncidentType.UNKNOWN
