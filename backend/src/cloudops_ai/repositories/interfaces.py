"""Incident repository interface.

Kept as a Protocol (structural typing), same pattern as tools/interfaces.py
-- the in-memory implementation and the eventual DynamoDB implementation
just need matching method signatures, no shared base class required.
"""

from __future__ import annotations

from typing import Protocol

from cloudops_ai.domain.models.incident import IncidentState


class IIncidentRepository(Protocol):
    """Persistence boundary for IncidentState. Routers and services depend
    on this, never on a concrete implementation.
    """

    def save(self, incident: IncidentState) -> None: ...

    def get(self, incident_id: str) -> IncidentState | None: ...

    def list_all(self) -> list[IncidentState]: ...
