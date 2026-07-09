"""Bridges real AWS signals into the incident pipeline via SQS.

This is the actual EventBridge -> SQS -> ECS pipeline api/routers/incidents.py's
docstring refers to as "not built yet." CloudWatch Alarms entering ALARM
state and GuardDuty findings above a severity threshold land on one SQS
queue (infra/modules/eventbridge) that `SQSIncidentPoller` below long-polls
from a background asyncio task (started in main.py's lifespan, only when
CLOUDOPS_SQS_QUEUE_URL is set).

Deliberately NOT a Lambda calling POST /incidents over HTTP: the ECS
service has no ALB and no stable DNS name (its public IP changes on every
redeploy -- see infra/README.md). Polling SQS under the backend's own IAM
role sidesteps that entirely; nothing external needs to know the task's
current address.

Each message, once parsed into an IncidentState, is run through the exact
same `graph.invoke()` call the manual API endpoint uses -- this file's only
job is translating an AWS event into an IncidentState and a resource
reference; classification, investigation, and remediation gating are all
unchanged, shared code.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any

import boto3
import structlog
from langchain_core.language_models import BaseChatModel

from cloudops_ai.agents.graph import build_graph
from cloudops_ai.agents.state import build_initial_state
from cloudops_ai.core.config import Settings
from cloudops_ai.domain.enums import TriggerSource
from cloudops_ai.domain.models.incident import IncidentState
from cloudops_ai.domain.models.resource import ResourceRef
from cloudops_ai.repositories.interfaces import IIncidentRepository
from cloudops_ai.tools.interfaces import IReadOnlyAWSTools

logger = structlog.get_logger(__name__)

_LONG_POLL_WAIT_SECONDS = 20
_MAX_MESSAGES_PER_POLL = 10


def _find_ec2_instance_id(node: Any) -> str | None:
    """Best-effort recursive search for an 'InstanceId' key anywhere inside
    a CloudWatch Alarm event's `detail`. Alarm shapes vary a lot depending
    on whether it's a plain-metric alarm, a metric-math alarm, or an
    anomaly-detection alarm -- this covers all of them without needing a
    hand-written case for each.
    """
    if isinstance(node, dict):
        if isinstance(node.get("InstanceId"), str):
            return node["InstanceId"]
        for value in node.values():
            found = _find_ec2_instance_id(value)
            if found:
                return found
    elif isinstance(node, list):
        for item in node:
            found = _find_ec2_instance_id(item)
            if found:
                return found
    return None


def _resource_from_alarm_event(event: dict[str, Any]) -> ResourceRef:
    """If the alarm's metric dimensions name an EC2 instance, build a
    proper instance ARN. Otherwise, fall back to the alarm's own ARN
    (always present in the EventBridge envelope's `resources` list) --
    less specific, but still a real, well-formed resource for the graph to
    reason about, rather than fabricating an EC2 ARN that doesn't
    correspond to anything.
    """
    region = event.get("region", "us-east-1")
    account_id = event.get("account", "000000000000")
    detail = event.get("detail", {})

    instance_id = _find_ec2_instance_id(detail.get("configuration", {}))
    if instance_id:
        return ResourceRef(
            arn=f"arn:aws:ec2:{region}:{account_id}:instance/{instance_id}",
            resource_type="AWS::EC2::Instance",
            region=region,
            account_id=account_id,
        )

    resources = event.get("resources") or []
    alarm_arn = resources[0] if resources else (
        f"arn:aws:cloudwatch:{region}:{account_id}:alarm:{detail.get('alarmName', 'unknown')}"
    )
    return ResourceRef(
        arn=alarm_arn,
        resource_type="AWS::CloudWatch::Alarm",
        region=region,
        account_id=account_id,
        name=detail.get("alarmName"),
    )


def _resource_from_guardduty_event(event: dict[str, Any]) -> ResourceRef:
    """GuardDuty findings nest resource details under type-specific keys
    (instanceDetails, s3BucketDetails, accessKeyDetails, ...) rather than
    one consistent shape. This covers the two cases this project's Security
    Agent already knows how to investigate (EC2, S3) and falls back to the
    finding's own ARN otherwise -- honest about not having identified a
    specific underlying resource, rather than guessing one.
    """
    region = event.get("region", "us-east-1")
    account_id = event.get("account", "000000000000")
    detail = event.get("detail", {})
    resource = detail.get("resource", {})

    instance_id = (resource.get("instanceDetails") or {}).get("instanceId")
    if instance_id:
        return ResourceRef(
            arn=f"arn:aws:ec2:{region}:{account_id}:instance/{instance_id}",
            resource_type="AWS::EC2::Instance",
            region=region,
            account_id=account_id,
        )

    s3_buckets = resource.get("s3BucketDetails") or []
    if s3_buckets and s3_buckets[0].get("arn"):
        return ResourceRef(
            arn=s3_buckets[0]["arn"],
            resource_type="AWS::S3::Bucket",
            region=region,
            account_id=account_id,
            name=s3_buckets[0].get("name"),
        )

    finding_arn = detail.get(
        "arn", f"arn:aws:guardduty:{region}:{account_id}:detector/unknown/finding/unknown"
    )
    return ResourceRef(
        arn=finding_arn,
        resource_type="AWS::GuardDuty::Finding",
        region=region,
        account_id=account_id,
        name=detail.get("title"),
    )


def build_incident_from_event(event: dict[str, Any]) -> IncidentState | None:
    """Translate one EventBridge event (already JSON-decoded from an SQS
    message body) into a fresh IncidentState, ready for `graph.invoke()` --
    the same entry point api/routers/incidents.py's POST handler uses, just
    triggered by a real AWS signal instead of a curl command.

    Returns None for a detail-type this poller doesn't know how to handle.
    Defensive, not dead code: the queue's EventBridge rules are already
    filtered to exactly two detail-types, but a hand-sent test message, or
    a future rule added without a matching case here, shouldn't crash the
    poll loop.
    """
    detail_type = event.get("detail-type")

    if detail_type == "CloudWatch Alarm State Change":
        trigger_source = TriggerSource.CLOUDWATCH_ALARM
        resource = _resource_from_alarm_event(event)
    elif detail_type == "GuardDuty Finding":
        trigger_source = TriggerSource.GUARDDUTY_FINDING
        resource = _resource_from_guardduty_event(event)
    else:
        logger.warning("sqs_poller.unknown_detail_type", detail_type=detail_type)
        return None

    return IncidentState(
        incident_id=str(uuid.uuid4()),
        trigger_source=trigger_source,
        affected_resources=[resource],
        raw_trigger_payload=event,
    )


class SQSIncidentPoller:
    """Long-polls the incident-triggers queue and, for each message, runs
    it through the same agent graph the manual API endpoint uses.

    A class, not a bare function, specifically so tests can call
    `poll_once()` directly -- exercising one batch of messages
    synchronously -- without needing to spin up and cancel a real asyncio
    background task.
    """

    def __init__(
        self,
        settings: Settings,
        repo: IIncidentRepository,
        aws_tools: IReadOnlyAWSTools,
        chat_model: BaseChatModel,
    ) -> None:
        if not settings.sqs_queue_url:
            raise ValueError("SQSIncidentPoller requires settings.sqs_queue_url to be set")
        self._queue_url = settings.sqs_queue_url
        self._repo = repo
        self._aws_tools = aws_tools
        self._chat_model = chat_model
        self._sqs = boto3.client("sqs", region_name=settings.aws_region)

    def poll_once(self) -> int:
        """Receive and process one batch of messages (up to 10, SQS's
        max). Returns the number of messages received. Synchronous and
        blocking -- `run_forever` wraps this for use inside an asyncio
        event loop without blocking it.
        """
        response = self._sqs.receive_message(
            QueueUrl=self._queue_url,
            MaxNumberOfMessages=_MAX_MESSAGES_PER_POLL,
            WaitTimeSeconds=_LONG_POLL_WAIT_SECONDS,
        )
        messages = response.get("Messages", [])

        for message in messages:
            self._process_message(message)

        return len(messages)

    def _process_message(self, message: dict[str, Any]) -> None:
        receipt_handle = message["ReceiptHandle"]
        try:
            event = json.loads(message["Body"])
            incident = build_incident_from_event(event)
            if incident is None:
                # Not a detail-type we handle -- delete rather than let it
                # sit and redrive to the DLQ for something we already know
                # we're never going to process.
                self._sqs.delete_message(QueueUrl=self._queue_url, ReceiptHandle=receipt_handle)
                return

            graph = build_graph(chat_model=self._chat_model, aws_tools=self._aws_tools)
            result = graph.invoke(build_initial_state(incident))
            final_incident = result["incident"]
            self._repo.save(final_incident)

            logger.info(
                "sqs_poller.incident_created",
                incident_id=final_incident.incident_id,
                incident_type=final_incident.incident_type.value,
                trigger_source=final_incident.trigger_source.value,
            )
            self._sqs.delete_message(QueueUrl=self._queue_url, ReceiptHandle=receipt_handle)
        except Exception:
            # Deliberately NOT deleting the message here -- leaving it to
            # become visible again (after visibility_timeout_seconds
            # elapses) so it gets retried, up to max_receive_count times,
            # before the eventbridge module's redrive policy moves it to
            # the DLQ. A message that fails due to a transient error (LLM
            # API blip, DynamoDB throttle) deserves a retry; silently
            # dropping it here would just lose the incident trigger.
            logger.exception("sqs_poller.message_processing_failed", message_id=message.get("MessageId"))

    async def run_forever(self) -> None:
        """The actual background task -- an infinite long-poll loop. Each
        blocking `receive_message` call runs in a thread so it doesn't
        stall the FastAPI event loop for up to 20 seconds at a time.
        """
        logger.info("sqs_poller.started", queue_url=self._queue_url)
        while True:
            try:
                await asyncio.to_thread(self.poll_once)
            except asyncio.CancelledError:
                logger.info("sqs_poller.stopped")
                raise
            except Exception:
                # A poll_once() failure here means receive_message itself
                # failed (network blip, throttling) -- not an individual
                # message failing, which _process_message already handles
                # separately. Log and keep looping rather than let one bad
                # poll kill the background task for the app's remaining
                # lifetime.
                logger.exception("sqs_poller.poll_failed")
                await asyncio.sleep(5)
