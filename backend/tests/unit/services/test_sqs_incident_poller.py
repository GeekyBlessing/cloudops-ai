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


_GUARDDUTY_EVENT_WITH_S3_BUCKET = {
    "version": "0",
    "detail-type": "GuardDuty Finding",
    "source": "aws.guardduty",
    "account": "123456789012",
    "region": "us-east-1",
    "resources": [],
    "detail": {
        "type": "Policy:S3/BucketPublic",
        "title": "S3 bucket is publicly accessible",
        "severity": 5.0,
        "arn": "arn:aws:guardduty:us-east-1:123456789012:detector/d1/finding/f3",
        "resource": {
            "s3BucketDetails": [
                {"arn": "arn:aws:s3:::my-exposed-bucket", "name": "my-exposed-bucket"}
            ]
        },
    },
}

_UNKNOWN_DETAIL_TYPE_EVENT = {
    "version": "0",
    "detail-type": "Something Else Entirely",
    "source": "aws.somewhere",
    "account": "123456789012",
    "region": "us-east-1",
    "resources": [],
    "detail": {},
}


def test_guardduty_event_with_s3_bucket_details_builds_s3_resource() -> None:
    """The s3BucketDetails branch of _resource_from_guardduty_event has no
    test yet -- only the EC2 and unrecognized-fallback branches do.
    """
    incident = build_incident_from_event(_GUARDDUTY_EVENT_WITH_S3_BUCKET)
    assert incident is not None
    assert incident.affected_resources[0].arn == "arn:aws:s3:::my-exposed-bucket"
    assert incident.affected_resources[0].resource_type == "AWS::S3::Bucket"
    assert incident.affected_resources[0].name == "my-exposed-bucket"


@mock_aws
def test_poll_once_deletes_message_with_unknown_detail_type_without_creating_incident() -> None:
    """build_incident_from_event returning None for an unrecognized
    detail-type is already covered directly (test_unknown_detail_type_returns_none
    above) -- this covers the other half: _process_message must still
    delete that message from the queue rather than leave it to redrive to
    the DLQ for something it already knows it will never process.
    """
    sqs = boto3.client("sqs", region_name="us-east-1")
    queue_url = sqs.create_queue(QueueName="incident-triggers")["QueueUrl"]
    sqs.send_message(QueueUrl=queue_url, MessageBody=json.dumps(_UNKNOWN_DETAIL_TYPE_EVENT))
    settings = Settings(sqs_queue_url=queue_url, aws_region="us-east-1")
    repo = InMemoryIncidentRepository()
    aws_tools = MockAWSGateway()
    chat_model = FakeListChatModel(responses=[])
    poller = SQSIncidentPoller(settings=settings, repo=repo, aws_tools=aws_tools, chat_model=chat_model)

    processed = poller.poll_once()

    assert processed == 1
    assert repo.list_all() == []
    remaining = sqs.receive_message(QueueUrl=queue_url, WaitTimeSeconds=0)
    assert "Messages" not in remaining


# --- run_forever: the background loop itself --------------------------------
# poll_once() is tested exhaustively above; run_forever is a thin async
# wrapper (asyncio.to_thread + CancelledError propagation + retry-after-
# failure), untested until now since nothing else in this file exercises it.


@pytest.mark.asyncio
async def test_run_forever_propagates_cancellation_cleanly() -> None:
    import asyncio

    settings = Settings(sqs_queue_url="https://sqs.us-east-1.amazonaws.com/123456789012/test-queue")
    repo = InMemoryIncidentRepository()
    aws_tools = MockAWSGateway()
    chat_model = FakeListChatModel(responses=[])
    poller = SQSIncidentPoller(settings=settings, repo=repo, aws_tools=aws_tools, chat_model=chat_model)
    poller.poll_once = lambda: 0

    task = asyncio.create_task(poller.run_forever())
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_run_forever_logs_and_keeps_looping_after_poll_once_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A poll_once() failure (receive_message itself failing -- network
    blip, throttling) must not kill the background task for the rest of
    the app's lifetime -- it logs and keeps looping.
    Uses the real asyncio.to_thread (genuine executor-based scheduling,
    which actually yields to the event loop when the thread completes --
    a fake no-await stub would not) and only short-circuits the specific
    5-second retry delay, so the test doesn't need to wait 5 real seconds
    per loop iteration to observe a second call.
    """
    import asyncio

    settings = Settings(sqs_queue_url="https://sqs.us-east-1.amazonaws.com/123456789012/test-queue")
    repo = InMemoryIncidentRepository()
    aws_tools = MockAWSGateway()
    chat_model = FakeListChatModel(responses=[])
    poller = SQSIncidentPoller(settings=settings, repo=repo, aws_tools=aws_tools, chat_model=chat_model)

    call_count = 0

    def _always_fails() -> int:
        nonlocal call_count
        call_count += 1
        raise RuntimeError("simulated receive_message failure")

    poller.poll_once = _always_fails

    real_sleep = asyncio.sleep

    async def _skip_the_five_second_retry_delay(seconds: float) -> None:
        if seconds == 5:
            return
        await real_sleep(seconds)

    monkeypatch.setattr(asyncio, "sleep", _skip_the_five_second_retry_delay)

    task = asyncio.create_task(poller.run_forever())
    for _ in range(50):
        await asyncio.sleep(0.01)
        if call_count >= 2:
            break
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert call_count >= 2
