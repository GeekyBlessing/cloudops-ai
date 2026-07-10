"""Domain-level enumerations shared across the entire agent system.

These enums are intentionally framework-free (no boto3, no LangGraph, no
FastAPI imports) so they can be imported by any layer -- domain, services,
agents, API schemas -- without creating a dependency cycle back into
infrastructure code.
"""

from __future__ import annotations

from enum import StrEnum


class IncidentType(StrEnum):
    """The catalogue of incident types CloudOps AI knows how to handle.

    Adding a new incident type is meant to be a three-step process, by design:
      1. Add the member here.
      2. Add an entry to REMEDIATION_POLICY (domain/policies/remediation_policy.py)
         describing which actions are allowed for it.
      3. Register a classification rule in the Coordinator agent's prompt/routing.
    No other code should need to change -- that's what "Open/Closed" looks
    like in an agentic system: closed for modification of the graph itself,
    open for extension via policy + prompt data.
    """

    EC2_HIGH_CPU = "ec2_high_cpu"
    EC2_DOWN = "ec2_down"
    PUBLIC_S3_BUCKET = "public_s3_bucket"
    IAM_MISCONFIGURATION = "iam_misconfiguration"
    HIGH_BILLING = "high_billing"
    LAMBDA_ERRORS = "lambda_errors"
    RDS_STORAGE_FULL = "rds_storage_full"
    AUTO_SCALING_FAILURE = "auto_scaling_failure"
    # This project's own operational health alarms (infra/modules/monitoring
    # -- ECS CPU/memory, the incident-triggers DLQ, SQS poller staleness)
    # feeding back into this same pipeline via infra/modules/eventbridge's
    # unscoped CloudWatch-Alarm-state-change rule. Assigned deterministically
    # in coordinator.py's classify_node, never by the LLM -- see that
    # module's docstring. Deliberately absent from graph.py's
    # _SPECIALIST_ROUTING and remediation_policy.py's REMEDIATION_POLICY: a
    # platform alarm should never trigger an investigation with tools built
    # for customer AWS resources, or a proposed remediation action. It
    # routes straight to "decide", which fails closed with no policy entry.
    PLATFORM_HEALTH_ALARM = "platform_health_alarm"
    UNKNOWN = "unknown"  # Coordinator hasn't classified this incident yet, or couldn't


class Severity(StrEnum):
    """Incident severity, used for both prioritization and remediation gating.

    Deliberately coarse (4 levels, not a continuous score) because severity
    drives concrete branching logic -- e.g. "CRITICAL always requires human
    approval regardless of what the policy table says" -- and coarse enums
    are far easier to reason about and unit-test than a continuous score.
    """

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class TriggerSource(StrEnum):
    """Where an incident originated. Drives how the Coordinator seeds the
    initial evidence and which agent gets invoked first."""

    CLOUDWATCH_ALARM = "cloudwatch_alarm"
    GUARDDUTY_FINDING = "guardduty_finding"
    SCHEDULED_SCAN = "scheduled_scan"
    MANUAL = "manual"  # a human opened an incident via the dashboard/API directly


class RemediationStatus(StrEnum):
    """Lifecycle states of a RemediationPlan.

    Transition *rules* (which states can move to which) are enforced in
    services/remediation_service.py, not here -- this enum only names the
    states, so the domain model stays a pure data holder and the workflow
    logic lives in exactly one place.
    """

    NOT_STARTED = "not_started"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXECUTING = "executing"
    VERIFIED = "verified"
    FAILED = "failed"
    ESCALATED = "escalated"  # verification timed out without resolution


class RemediationMode(StrEnum):
    """Global execution mode for the Remediation Executor's tool binding.

    Read once at process startup from core/config.py (env var
    REMEDIATION_MODE) and never changed per-request -- that would defeat the
    point of a safety default that can't be overridden by a clever prompt or
    a single mistaken API call.
    """

    DRY_RUN = "dry_run"
    LIVE = "live"


class AgentName(StrEnum):
    """Canonical identifiers for each node in the LangGraph agent graph.

    Used in AgentStep.agent and Evidence.agent so the audit trail is
    queryable/filterable by agent, e.g. "show me everything the Security
    Agent found for this incident."
    """

    COORDINATOR = "coordinator"
    INFRASTRUCTURE = "infrastructure"
    MONITORING = "monitoring"
    TROUBLESHOOTING = "troubleshooting"
    SECURITY = "security"
    COST = "cost"
    DEPLOYMENT = "deployment"
    REMEDIATION_EXECUTOR = "remediation_executor"
