"""LangGraph state schema.

LangGraph drives a graph off a single object it can pass to every node and
get an update back from. We wrap the domain's IncidentState in a thin
TypedDict (`GraphState`) rather than handing IncidentState to StateGraph
directly, for one practical reason: LangGraph's default merge behavior for
TypedDict fields is "replace unless annotated with a reducer," and wrapping
the whole domain object under one key means each node simply returns
`{"incident": <updated IncidentState>}` and LangGraph replaces that key
wholesale -- which is exactly the semantics we want, since the domain
model's own methods (`add_evidence`, `add_agent_step`) already implement
the correct append-only merge logic internally, in Python, before LangGraph
ever sees the result.
"""

from __future__ import annotations

from typing import TypedDict

from cloudops_ai.domain.models.incident import IncidentState


class GraphState(TypedDict):
    """The object LangGraph actually threads through the compiled graph."""

    incident: IncidentState


def build_initial_state(incident: IncidentState) -> GraphState:
    """Wrap a freshly created IncidentState for a `graph.invoke()` call."""
    return {"incident": incident}
