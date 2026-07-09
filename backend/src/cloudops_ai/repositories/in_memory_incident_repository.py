"""In-memory IncidentState repository.

Deliberate placeholder: satisfies IIncidentRepository so every router and
service can be built and tested against it today, and gets swapped for a
real DynamoDB-backed implementation in the next build step without any
calling code changing -- same Dependency Inversion pattern as the mock AWS
gateway in adapters/mock/.
"""

from __future__ import annotations

from cloudops_ai.domain.models.incident import IncidentState


class InMemoryIncidentRepository:
    """Process-local, non-persistent store.

    Data is lost on restart -- fine for local development and this initial
    FastAPI shell, not acceptable for anything beyond that. That limitation
    is the entire reason this class exists as a separate, clearly-named
    thing rather than being called "the" repository.
    """

    def __init__(self) -> None:
        self._incidents: dict[str, IncidentState] = {}

    def save(self, incident: IncidentState) -> None:
        self._incidents[incident.incident_id] = incident

    def get(self, incident_id: str) -> IncidentState | None:
        return self._incidents.get(incident_id)

    def list_all(self) -> list[IncidentState]:
        """Most recent first -- matches what the dashboard's incident list
        view wants by default.
        """
        return sorted(self._incidents.values(), key=lambda incident: incident.created_at, reverse=True)
