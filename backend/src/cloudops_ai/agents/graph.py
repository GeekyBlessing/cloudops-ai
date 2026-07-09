"""LangGraph StateGraph assembly.

classify -> route to the specialist agent relevant to the classified
incident_type -> decide. Each specialist is a plain function node (built by
its own factory in agents/*.py); the routing table below is the only place
that knows which specialist handles which incident_type -- adding a new
incident type touches this file plus REMEDIATION_POLICY, not any existing
agent's code (Open/Closed again, this time at the graph level instead of
the policy-table level).

Unrouted incident types (UNKNOWN, and anything without dedicated specialist
logic) go straight from classify to decide -- decide_node already fails
closed (no remediation policy entry -> no plan proposed), so skipping
straight to it is safe, not a shortcut around any check.
"""

from __future__ import annotations

from langchain_core.language_models import BaseChatModel
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from cloudops_ai.agents.coordinator import make_classify_node, make_decide_node
from cloudops_ai.agents.cost_agent import make_cost_node
from cloudops_ai.agents.deployment_agent import make_deployment_node
from cloudops_ai.agents.infrastructure_agent import make_infrastructure_node
from cloudops_ai.agents.monitoring_agent import make_monitoring_node
from cloudops_ai.agents.security_agent import make_security_node
from cloudops_ai.agents.state import GraphState
from cloudops_ai.agents.troubleshooting_agent import make_troubleshooting_node
from cloudops_ai.domain.enums import IncidentType
from cloudops_ai.tools.interfaces import IReadOnlyAWSTools

# incident_type -> specialist node name. Anything not listed here (including
# UNKNOWN) routes straight to "decide" -- see module docstring.
_SPECIALIST_ROUTING: dict[IncidentType, str] = {
    IncidentType.EC2_HIGH_CPU: "monitoring",
    IncidentType.EC2_DOWN: "infrastructure",
    IncidentType.RDS_STORAGE_FULL: "infrastructure",
    IncidentType.PUBLIC_S3_BUCKET: "security",
    IncidentType.IAM_MISCONFIGURATION: "security",
    IncidentType.LAMBDA_ERRORS: "troubleshooting",
    IncidentType.AUTO_SCALING_FAILURE: "deployment",
    IncidentType.HIGH_BILLING: "cost",
}


def _route_after_classify(state: GraphState) -> str:
    """Conditional-edge function: decide which specialist node runs next
    based on what the Coordinator just classified this incident as.
    """
    incident_type = state["incident"].incident_type
    return _SPECIALIST_ROUTING.get(incident_type, "decide")


def build_graph(chat_model: BaseChatModel, aws_tools: IReadOnlyAWSTools) -> CompiledStateGraph:
    """Assemble and compile the full graph: classify -> (routed specialist) -> decide.

    `chat_model` and `aws_tools` are injected here, not imported inside the
    node modules -- this is the one place in the codebase that decides
    "real AWS + real Claude" vs. "mock AWS + fake chat model," and every
    other file stays agnostic to that choice. Swapping environments is a
    different call to `build_graph`, not a different version of any node.
    """
    graph: StateGraph = StateGraph(GraphState)

    graph.add_node("classify", make_classify_node(chat_model))
    graph.add_node("monitoring", make_monitoring_node(aws_tools))
    graph.add_node("infrastructure", make_infrastructure_node(aws_tools))
    graph.add_node("security", make_security_node(aws_tools))
    graph.add_node("troubleshooting", make_troubleshooting_node(aws_tools))
    graph.add_node("deployment", make_deployment_node(aws_tools))
    graph.add_node("cost", make_cost_node(aws_tools))
    graph.add_node("decide", make_decide_node(chat_model))

    graph.add_edge(START, "classify")
    graph.add_conditional_edges(
        "classify",
        _route_after_classify,
        {
            "monitoring": "monitoring",
            "infrastructure": "infrastructure",
            "security": "security",
            "troubleshooting": "troubleshooting",
            "deployment": "deployment",
            "cost": "cost",
            "decide": "decide",
        },
    )
    for specialist_node in ("monitoring", "infrastructure", "security", "troubleshooting", "deployment", "cost"):
        graph.add_edge(specialist_node, "decide")
    graph.add_edge("decide", END)

    return graph.compile()
