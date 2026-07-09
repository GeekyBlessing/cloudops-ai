"""Unit tests for the Coordinator's classify_node -- specifically the
classification prompt payload, not the LLM's response handling (test_graph.py
already covers end-to-end classification with a FakeListChatModel).

These tests exist because of a real bug found while building the
EventBridge/SQS trigger pipeline: classify_node used to build its prompt
from only `incident_id` and `trigger_source`, so a real CloudWatch Alarm or
GuardDuty Finding delivered via SQS would be classified blind -- none of
the alarm/finding detail ever reached the LLM. See coordinator.py's
docstring for the full explanation.
"""

from __future__ import annotations

from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from cloudops_ai.agents.coordinator import make_classify_node
from cloudops_ai.agents.state import build_initial_state
from cloudops_ai.domain.enums import TriggerSource
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
