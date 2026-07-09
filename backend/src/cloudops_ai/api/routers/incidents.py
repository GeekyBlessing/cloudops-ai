"""`/incidents` router.

Exposes list, get-one, and create-and-run. "Create" synchronously drives the
incident through the full LangGraph skeleton (classify -> gather_metrics ->
decide) and returns the finished IncidentState -- there's no background
worker/queue yet (that's the EventBridge -> SQS -> ECS pipeline described in
/docs/ARCHITECTURE.md), so for now this endpoint IS the pipeline, callable
directly over HTTP. That's a deliberate, temporary simplification, not an
architectural claim about how this should work in production.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from langchain_core.language_models import BaseChatModel
from pydantic import BaseModel, Field

from cloudops_ai.agents.graph import build_graph
from cloudops_ai.agents.state import build_initial_state
from cloudops_ai.api.dependencies import get_aws_tools, get_chat_model, get_incident_repository
from cloudops_ai.domain.enums import TriggerSource
from cloudops_ai.domain.models.incident import IncidentState
from cloudops_ai.domain.models.resource import ResourceRef
from cloudops_ai.repositories.interfaces import IIncidentRepository
from cloudops_ai.tools.interfaces import IReadOnlyAWSTools

router = APIRouter(prefix="/incidents", tags=["incidents"])


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

    Synchronous-and-blocking is a known, called-out limitation: a real
    deployment runs this off the EventBridge -> SQS -> ECS pipeline, not
    inline in a request handler. This endpoint exists so the whole pipeline
    is exercisable with one curl command during development.
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
