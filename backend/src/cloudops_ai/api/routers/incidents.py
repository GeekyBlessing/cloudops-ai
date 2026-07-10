"""`/incidents` router.

Exposes list, get-one, and create-and-run. "Create" synchronously drives the
incident through the full LangGraph skeleton (classify -> gather_metrics ->
decide) and returns the finished IncidentState. This is the manual/API entry
point -- a curl command or the dashboard's "New incident" form. The other
entry point, services/sqs_incident_poller.py, drives the exact same graph
from real CloudWatch Alarms/GuardDuty findings via EventBridge -> SQS; this
router doesn't need to know that path exists, since both converge on the
same IncidentState/graph.invoke() machinery.

Protected by require_api_key (api/dependencies.py) when CLOUDOPS_API_KEY is
set -- a no-op otherwise.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from langchain_core.language_models import BaseChatModel
from pydantic import BaseModel, Field

from cloudops_ai.agents.graph import build_graph
from cloudops_ai.agents.state import build_initial_state
from cloudops_ai.api.dependencies import (
    get_aws_tools,
    get_chat_model,
    get_incident_repository,
    require_api_key,
)
from cloudops_ai.domain.enums import TriggerSource
from cloudops_ai.domain.models.incident import IncidentState
from cloudops_ai.domain.models.resource import ResourceRef
from cloudops_ai.repositories.interfaces import IIncidentRepository
from cloudops_ai.tools.interfaces import IReadOnlyAWSTools

# dependencies=[...] applies require_api_key to every route on this router --
# a no-op when settings.api_key is None (the default), a 401 gate otherwise.
# See api/dependencies.py's require_api_key docstring for why this is a
# router-level dependency rather than app-wide middleware.
router = APIRouter(prefix="/incidents", tags=["incidents"], dependencies=[Depends(require_api_key)])


class IncidentSummary(BaseModel):
    """Lightweight shape for the incident list view -- deliberately smaller
    than the full IncidentState so the list endpoint stays cheap even once
    evidence/agent_trace grow large on individual incidents.
    """

    incident_id: str
    incident_type: str
    severity: str | None
    remediation_status: str
    created_at: str

    @classmethod
    def from_incident(cls, incident: IncidentState) -> IncidentSummary:
        return cls(
            incident_id=incident.incident_id,
            incident_type=incident.incident_type.value,
            severity=incident.severity.value if incident.severity else None,
            remediation_status=incident.remediation_status.value,
            created_at=incident.created_at.isoformat(),
        )


class CreateIncidentRequest(BaseModel):
    """Manual incident trigger -- stands in for what a real CloudWatch
    Alarm/EventBridge payload would populate once that pipeline exists.
    """

    trigger_source: TriggerSource = TriggerSource.MANUAL
    instance_arn: str = Field(description="ARN of the affected EC2 instance, e.g. for an EC2 High CPU scenario")


@router.get("", response_model=list[IncidentSummary])
def list_incidents(repo: IIncidentRepository = Depends(get_incident_repository)) -> list[IncidentSummary]:
    """List all incidents, most recent first."""
    return [IncidentSummary.from_incident(incident) for incident in repo.list_all()]


@router.get("/{incident_id}", response_model=IncidentState)
def get_incident(
    incident_id: str, repo: IIncidentRepository = Depends(get_incident_repository)
) -> IncidentState:
    """Fetch the full incident record, including evidence and agent_trace."""
    incident = repo.get(incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail=f"No incident with id {incident_id!r}")
    return incident


@router.post("", response_model=IncidentState, status_code=201)
def create_incident(
    request: CreateIncidentRequest,
    repo: IIncidentRepository = Depends(get_incident_repository),
    chat_model: BaseChatModel = Depends(get_chat_model),
    aws_tools: IReadOnlyAWSTools = Depends(get_aws_tools),
) -> IncidentState:
    """Create a new incident and synchronously run it through the agent graph.

    Synchronous-and-blocking is a known, deliberate limitation of THIS entry
    point specifically -- real AWS-triggered incidents go through
    services/sqs_incident_poller.py's background task instead, which runs
    the same graph without blocking an HTTP request. This endpoint stays
    synchronous because its whole point is being exercisable with one curl
    command during development, where waiting a few seconds for a response
    is the more useful behavior than a fire-and-forget 202.
    """
    arn_parts = request.instance_arn.split(":")
    resource = ResourceRef(
        arn=request.instance_arn,
        resource_type="AWS::EC2::Instance",
        region=arn_parts[3] if len(arn_parts) > 3 else "us-east-1",
        account_id=arn_parts[4] if len(arn_parts) > 4 else "000000000000",
    )
    incident = IncidentState(
        incident_id=str(uuid.uuid4()),
        trigger_source=request.trigger_source,
        affected_resources=[resource],
    )

    graph = build_graph(chat_model=chat_model, aws_tools=aws_tools)
    result = graph.invoke(build_initial_state(incident))
    final_incident = result["incident"]

    repo.save(final_incident)
    return final_incident
