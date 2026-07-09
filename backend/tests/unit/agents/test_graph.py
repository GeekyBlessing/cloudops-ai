"""End-to-end tests of the full LangGraph: classify -> routed specialist ->
decide, run against the mock AWS gateway and a scripted fake chat model.

These are the tests that prove the whole pattern works together: typed
shared state flowing through real LangGraph nodes, dependency-injected
tools and LLM, conditional routing to the right specialist, and an
append-only audit trail -- without touching a real AWS account or a real
LLM API.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from langchain_core.language_models.fake_chat_models import FakeListChatModel

from cloudops_ai.adapters.mock.mock_aws_gateway import MockAWSGateway
from cloudops_ai.agents.graph import build_graph
from cloudops_ai.agents.state import build_initial_state
from cloudops_ai.domain.enums import IncidentType, RemediationStatus, Severity, TriggerSource
from cloudops_ai.domain.models.incident import IncidentState
from cloudops_ai.domain.models.resource import ResourceRef


def test_ec2_high_cpu_incident_is_classified_and_remediation_is_proposed() -> None:
    instance = ResourceRef(
        arn="arn:aws:ec2:us-east-1:123456789012:instance/i-0abcd1234",
        resource_type="AWS::EC2::Instance",
        region="us-east-1",
        account_id="123456789012",
        attributes={"state": "running"},
    )
    gateway = MockAWSGateway(seed_resources=[instance])
    now = datetime.now(timezone.utc)
    gateway.seed_metric_data(
        namespace="AWS/EC2",
        metric_name="CPUUtilization",
        dimensions={"InstanceId": "i-0abcd1234"},
        datapoints=[
            {"Timestamp": now.isoformat(), "Average": 96.2},
            {"Timestamp": now.isoformat(), "Average": 94.8},
        ],
    )

    # Scripted LLM responses, consumed in call order: first the
    # classification JSON, then the remediation rationale text.
    fake_llm = FakeListChatModel(
        responses=[
            '{"incident_type": "ec2_high_cpu", "severity": "high"}',
            "CPU has held above 94% for the observed window with no corresponding deploy event, "
            "indicating sustained load rather than a transient spike. Rebooting the instance is the "
            "lowest-risk first remediation before considering a scale-out.",
        ]
    )

    incident = IncidentState(
        incident_id="incident-1",
        trigger_source=TriggerSource.CLOUDWATCH_ALARM,
        affected_resources=[instance],
    )

    app = build_graph(chat_model=fake_llm, aws_tools=gateway)
    result = app.invoke(build_initial_state(incident))
    final_incident = result["incident"]

    assert final_incident.incident_type == IncidentType.EC2_HIGH_CPU
    assert final_incident.severity == Severity.HIGH

    assert len(final_incident.evidence) == 1
    assert final_incident.evidence[0].data["mean_cpu_percent"] == pytest.approx(95.5)

    assert final_incident.proposed_remediation is not None
    assert final_incident.proposed_remediation.actions[0].action_name == "reboot_instance"
    assert final_incident.proposed_remediation.actions[0].target_arn == instance.arn
    assert final_incident.remediation_status == RemediationStatus.AWAITING_APPROVAL

    # classify + monitoring + decide = 3 audit entries, in order.
    assert [step.agent.value for step in final_incident.agent_trace] == [
        "coordinator",
        "monitoring",
        "coordinator",
    ]


def test_incident_with_no_policy_entry_gets_no_remediation_plan() -> None:
    """HIGH_BILLING has no entries in the remediation policy table --
    verifies the Coordinator's decide_node fails closed (no plan) rather
    than guessing an action. Also exercises the classify -> cost -> decide
    routing path.
    """
    gateway = MockAWSGateway()
    fake_llm = FakeListChatModel(
        responses=['{"incident_type": "high_billing", "severity": "critical"}']
    )

    incident = IncidentState(incident_id="incident-2", trigger_source=TriggerSource.SCHEDULED_SCAN)

    app = build_graph(chat_model=fake_llm, aws_tools=gateway)
    result = app.invoke(build_initial_state(incident))
    final_incident = result["incident"]

    assert final_incident.incident_type == IncidentType.HIGH_BILLING
    assert final_incident.proposed_remediation is None
    assert final_incident.remediation_status == RemediationStatus.NOT_STARTED
    assert [step.agent.value for step in final_incident.agent_trace] == ["coordinator", "cost", "coordinator"]


def test_public_s3_bucket_incident_routes_to_security_agent() -> None:
    bucket = ResourceRef(
        arn="arn:aws:s3:::my-public-bucket",
        resource_type="AWS::S3::Bucket",
        region="us-east-1",
        account_id="123456789012",
        attributes={"is_public": True},
    )
    gateway = MockAWSGateway(seed_resources=[bucket])
    fake_llm = FakeListChatModel(
        responses=[
            '{"incident_type": "public_s3_bucket", "severity": "critical"}',
            "The bucket policy grants unauthenticated read access with no business justification found "
            "in evidence; revoking public access is the safe, reversible first step.",
        ]
    )

    incident = IncidentState(
        incident_id="incident-3",
        trigger_source=TriggerSource.GUARDDUTY_FINDING,
        affected_resources=[bucket],
    )

    app = build_graph(chat_model=fake_llm, aws_tools=gateway)
    result = app.invoke(build_initial_state(incident))
    final_incident = result["incident"]

    assert [step.agent.value for step in final_incident.agent_trace] == ["coordinator", "security", "coordinator"]
    assert final_incident.proposed_remediation is not None
    assert final_incident.proposed_remediation.actions[0].action_name == "revoke_public_access"


def test_ec2_down_incident_routes_to_infrastructure_agent() -> None:
    instance = ResourceRef(
        arn="arn:aws:ec2:us-east-1:123456789012:instance/i-0deadbeef",
        resource_type="AWS::EC2::Instance",
        region="us-east-1",
        account_id="123456789012",
        attributes={"state": "stopped"},
    )
    gateway = MockAWSGateway(seed_resources=[instance])
    fake_llm = FakeListChatModel(
        responses=[
            '{"incident_type": "ec2_down", "severity": "critical"}',
            "Instance state confirms it is stopped with no scheduled maintenance window recorded; "
            "starting it is the lowest-risk remediation.",
        ]
    )

    incident = IncidentState(
        incident_id="incident-4",
        trigger_source=TriggerSource.CLOUDWATCH_ALARM,
        affected_resources=[instance],
    )

    app = build_graph(chat_model=fake_llm, aws_tools=gateway)
    result = app.invoke(build_initial_state(incident))
    final_incident = result["incident"]

    assert [step.agent.value for step in final_incident.agent_trace] == [
        "coordinator",
        "infrastructure",
        "coordinator",
    ]
    assert final_incident.proposed_remediation.actions[0].action_name in {"start_instance", "reboot_instance"}


def test_unknown_incident_type_skips_specialists_straight_to_decide() -> None:
    """An UNKNOWN classification (e.g. the LLM's output didn't parse) has
    no entry in the specialist routing table -- the graph must go straight
    from classify to decide rather than erroring or hanging.
    """
    gateway = MockAWSGateway()
    fake_llm = FakeListChatModel(responses=["not valid json"])

    incident = IncidentState(incident_id="incident-5", trigger_source=TriggerSource.MANUAL)

    app = build_graph(chat_model=fake_llm, aws_tools=gateway)
    result = app.invoke(build_initial_state(incident))
    final_incident = result["incident"]

    assert final_incident.incident_type == IncidentType.UNKNOWN
    assert [step.agent.value for step in final_incident.agent_trace] == ["coordinator", "coordinator"]
