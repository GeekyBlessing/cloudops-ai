"""DynamoDB-backed IncidentState repository.

Replaces InMemoryIncidentRepository as the real persistence layer. Storage
strategy: a handful of top-level attributes the dashboard actually
queries/sorts on (incident_id as partition key, incident_type, severity,
remediation_status, created_at) plus one "document" attribute holding the
full IncidentState as a JSON blob. This is a deliberate middle ground
between "model every nested field as a DynamoDB attribute" (brittle --
every domain model change becomes a migration) and "store everything as an
opaque blob" (can't build a GSI or filter server-side on anything). See
/docs/ARCHITECTURE.md section 6 for the table's place in the wider system
(a GSI on status + created_at for the dashboard's incident list).
"""

from __future__ import annotations

from typing import Any

import boto3

from cloudops_ai.domain.models.incident import IncidentState


class DynamoDBIncidentRepository:
    """Implements IIncidentRepository (repositories/interfaces.py) against a
    real DynamoDB table, or DynamoDB Local when `endpoint_url` is set.
    """

    def __init__(self, table_name: str, region: str, endpoint_url: str | None = None) -> None:
        """`endpoint_url` is the whole story for local dev vs. real AWS:
        point it at DynamoDB Local (e.g. http://localhost:8001) for
        docker-compose, or leave it None to let boto3 talk to real AWS
        DynamoDB using the process's normal credential chain (instance
        role in ECS, environment/SSO locally).
        """
        resource = boto3.resource("dynamodb", region_name=region, endpoint_url=endpoint_url)
        self._table = resource.Table(table_name)

    def save(self, incident: IncidentState) -> None:
        item = self._to_item(incident)
        self._table.put_item(Item=item)

    def get(self, incident_id: str) -> IncidentState | None:
        response = self._table.get_item(Key={"incident_id": incident_id})
        item = response.get("Item")
        if item is None:
            return None
        return self._from_item(item)

    def list_all(self) -> list[IncidentState]:
        """A full table scan -- acceptable at the incident volumes this
        system deals with (an on-call system handles tens to hundreds of
        incidents, not billions of rows), and simpler than maintaining a
        GSI before there's a real query pattern that needs one. Revisit
        (query the status-created_at GSI instead) if this table ever gets
        large enough for a scan to matter.
        """
        items: list[dict[str, Any]] = []
        response = self._table.scan()
        items.extend(response.get("Items", []))
        while "LastEvaluatedKey" in response:
            response = self._table.scan(ExclusiveStartKey=response["LastEvaluatedKey"])
            items.extend(response.get("Items", []))

        incidents = [self._from_item(item) for item in items]
        return sorted(incidents, key=lambda incident: incident.created_at, reverse=True)

    @staticmethod
    def _to_item(incident: IncidentState) -> dict[str, Any]:
        """Top-level queryable attributes + one JSON-blob attribute holding
        the full document. `model_dump_json()` (not `model_dump()`) so
        datetimes and nested enums serialize exactly the same way they
        would over the API, which is what lets `_from_item` round-trip them
        with `model_validate_json` below.
        """
        return {
            "incident_id": incident.incident_id,
            "incident_type": incident.incident_type.value,
            "severity": incident.severity.value if incident.severity else "unset",
            "remediation_status": incident.remediation_status.value,
            "created_at": incident.created_at.isoformat(),
            "document": incident.model_dump_json(),
        }

    @staticmethod
    def _from_item(item: dict[str, Any]) -> IncidentState:
        """The top-level attributes exist for querying; the document
        attribute is the actual source of truth on read, so this never
        needs to reconstruct an IncidentState field-by-field from scalar
        attributes (which would silently drop anything nested).
        """
        return IncidentState.model_validate_json(item["document"])
