"""Tests for the SQS incident-trigger poller.

Two layers, matching the module's own structure: pure event-parsing tests
(no AWS at all) for build_incident_from_event's resource-extraction logic,
and a moto-backed integration test of SQSIncidentPoller.poll_once() proving
a message on a real (mocked) SQS queue ends up as a saved, classified
incident with the message deleted.
"""

from __future__ import annotations

import json

import boto3
import pytest
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from moto import mock_aws

from cloudops_ai.adapters.mock.mock_aws_gateway import MockAWSGateway
from cloudops_ai.core.config import Settings
from cloudops_ai.domain.enums import TriggerSource
from cloudops_ai.repositories.in_memory_incident_repository import InMemoryIncidentRepository
from cloudops_ai.services.sqs_incident_poller import SQSIncidentPoller, build_incident_from_event

# --- build_incident_from_event: pure parsing, no AWS ------------------------

_ALARM_EVENT_WITH_INSTANCE_ID = {
    "version": "0",
    "detail-type": "CloudWatch Alarm State Change",
    "source": "aws.cloudwatch",
    "account": "123456789012",
    "region": "us-east-1",
    "resources": ["arn:aws:cloudwatch:us-east-1:123456789012:alarm:high-cpu-i-0abcd1234"],
    "detail": {
        "alarmName": "high-cpu-i-0abcd1234",
        "state": {"value": "ALARM", "reason": "Threshold crossed"},
        "configuration": {
            "metrics": [
                {
                    "metricStat": {
                        "metric": {
                            "namespace": "AWS/EC2",
                            "name": "CPUUtilization",
                            "dimensions": {"InstanceId": "i-0abcd1234"},
                        }
                    }
                }
            ]
        },
    },
}

_ALARM_EVENT_WITHOUT_INSTANCE_ID = {
    "version": "0",
    "detail-type": "CloudWatch Alarm State Change",
    "source": "aws.cloudwatch",
    "account": "123456789012",
    "region": "us-east-1",
    "resources": ["arn:aws:cloudwatch:us-east-1:123456789012:alarm:custom-metric-alarm"],
    "detail": {
        "alarmName": "custom-metric-alarm",
        "state": {"value": "ALARM", "reason": "Threshold crossed"},
        "configuration": {"metrics": []},
    },
}

_GUARDDUTY_EVENT_WITH_INSTANCE = {
    "version": "0",
    "detail-type": "GuardDuty Finding",
    "source": "aws.guardduty",
    "account": "123456789012",
    "region": "us-east-1",
    "resources": [],
    "detail": {
        "type": "UnauthorizedAccess:EC2/SSHBruteForce",
        "title": "SSH brute force against i-0abcd1234",
        "severity": 5.0,
        "arn": "arn:aws:guardduty:us-east-1:123456789012:detector/d1/finding/f1",
        "resource": {"instanceDetails": {"instanceId": "i-0abcd1234"}},
    },
}

_GUARDDUTY_EVENT_WITHOUT_KNOWN_RESOURCE_TYPE = {
    "version": "0",
    "detail-type": "GuardDuty Finding",
    "source": "aws.guardduty",
    "account": "123456789012",
    "region": "us-east-1",
    "resources": [],
    "detail": {
        "type": "Persistence:IAMUser/NetworkPermissions",
        "title": "Unusual IAM permission change",
        "severity": 5.0,
        "arn": "arn:aws:guardduty:us-east-1:123456789012:detector/d1/finding/f2",
        "resource": {"accessKeyDetails": {"userName": "some-user"}},
    },
}


def test_alarm_event_with_instance_id_builds_ec2_resource() -> None:
    incident = build_incident_from_event(_ALARM_EVENT_WITH_INSTANCE_ID)
    assert incident is not None
    assert incident.trigger_source == TriggerSource.CLOUDWATCH_ALARM
    assert incident.affected_resources[0].arn == "arn:aws:ec2:us-east-1:123456789012:instance/i-0abcd1234"
    assert incident.affected_resources[0].resource_type == "AWS::EC2::Instance"
    assert incident.raw_trigger_payload == _ALARM_EVENT_WITH_INSTANCE_ID


def test_alarm_event_without_instance_id_falls_back_to_alarm_arn() -> None:
    incident = build_incident_from_event(_ALARM_EVENT_WITHOUT_INSTANCE_ID)
    assert incident is not None
    assert incident.affected_resources[0].arn == (
        "arn:aws:cloudwatch:us-east-1:123456789012:alarm:custom-metric-alarm"
    )
    assert incident.affected_resources[0].resource_type == "AWS::CloudWatch::Alarm"


def test_guardduty_event_with_instance_details_builds_ec2_resource() -> None:
    incident = build_incident_from_event(_GUARDDUTY_EVENT_WITH_INSTANCE)
    assert incident is not None
    assert incident.trigger_source == TriggerSource.GUARDDUTY_FINDING
    assert incident.affected_resources[0].arn == "arn:aws:ec2:us-east-1:123456789012:instance/i-0abcd1234"


def test_guardduty_event_with_unrecognized_resource_type_falls_back_to_finding_arn() -> None:
    incident = build_incident_from_event(_GUARDDUTY_EVENT_WITHOUT_KNOWN_RESOURCE_TYPE)
    assert incident is not None
    assert incident.affected_resources[0].arn == "arn:aws:guardduty:us-east-1:123456789012:detector/d1/finding/f2"
    assert incident.affected_resources[0].resource_type == "AWS::GuardDuty::Finding"


def test_unknown_detail_type_returns_none() -> None:
    event = {"detail-type": "Something Else Entirely", "detail": {}}
    assert build_incident_from_event(event) is None


# --- SQSIncidentPoller.poll_once(): moto-backed integration ----------------


@mock_aws
def test_poll_once_processes_message_creates_incident_and_deletes_message() -> None:
    sqs = boto3.client("sqs", region_name="us-east-1")
    queue_url = sqs.create_queue(QueueName="incident-triggers")["QueueUrl"]
    sqs.send_message(QueueUrl=queue_url, MessageBody=json.dumps(_ALARM_EVENT_WITH_INSTANCE_ID))

    settings = Settings(sqs_queue_url=queue_url, aws_region="us-east-1")
    repo = InMemoryIncidentRepository()
    aws_tools = MockAWSGateway()
    chat_model = FakeListChatModel(responses=['{"incident_type": "ec2_high_cpu", "severity": "high"}'])

    poller = SQSIncidentPoller(settings=settings, repo=repo, aws_tools=aws_tools, chat_model=chat_model)
    processed = poller.poll_once()

    assert processed == 1
    saved = repo.list_all()
    assert len(saved) == 1
    assert saved[0].trigger_source == TriggerSource.CLOUDWATCH_ALARM
    assert saved[0].incident_type.value == "ec2_high_cpu"

    # Message should be gone -- deleted after successful processing.
    remaining = sqs.receive_message(QueueUrl=queue_url, WaitTimeSeconds=0)
    assert "Messages" not in remaining


@mock_aws
def test_poll_once_leaves_message_in_queue_on_processing_failure() -> None:
    """A message that fails to process (e.g. malformed JSON body) should
    NOT be deleted -- it needs to survive to be retried, up to the queue's
    max_receive_count, rather than being silently dropped.
    """
    sqs = boto3.client("sqs", region_name="us-east-1")
    queue_url = sqs.create_queue(QueueName="incident-triggers")["QueueUrl"]
    sqs.send_message(QueueUrl=queue_url, MessageBody="not valid json {{{")

    settings = Settings(sqs_queue_url=queue_url, aws_region="us-east-1")
    repo = InMemoryIncidentRepository()
    aws_tools = MockAWSGateway()
    chat_model = FakeListChatModel(responses=['{"incident_type": "unknown", "severity": "low"}'])

    poller = SQSIncidentPoller(settings=settings, repo=repo, aws_tools=aws_tools, chat_model=chat_model)
    poller.poll_once()

    assert repo.list_all() == []
    attrs = sqs.get_queue_attributes(QueueUrl=queue_url, AttributeNames=["ApproximateNumberOfMessages"])
    assert attrs["Attributes"]["ApproximateNumberOfMessages"] == "0"
    attrs_not_visible = sqs.get_queue_attributes(
        QueueUrl=queue_url, AttributeNames=["ApproximateNumberOfMessagesNotVisible"]
    )
    assert attrs_not_visible["Attributes"]["ApproximateNumberOfMessagesNotVisible"] == "1"


def test_poller_requires_sqs_queue_url() -> None:
    settings = Settings(sqs_queue_url=None)
    repo = InMemoryIncidentRepository()
    aws_tools = MockAWSGateway()
    chat_model = FakeListChatModel(responses=[])

    with pytest.raises(ValueError, match="sqs_queue_url"):
        SQSIncidentPoller(settings=settings, repo=repo, aws_tools=aws_tools, chat_model=chat_model)
