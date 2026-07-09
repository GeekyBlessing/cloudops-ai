"""Domain-level enumerations shared across the entire agent system."""

from __future__ import annotations

from enum import StrEnum


class IncidentType(StrEnum):
    """The catalogue of incident types CloudOps AI knows how to handle."""

    EC2_HIGH_CPU = "ec2_high_cpu"
    EC2_DOWN = "ec2_down"
    PUBLIC_S3_BUCKET = "public_s3_bucket"
    IAM_MISCONFIGURATION = "iam_misconfiguration"
    HIGH_BILLING = "high_billing"
    LAMBDA_ERRORS = "lambda_errors"
    RDS_STORAGE_FULL = "rds_storage_full"
    AUTO_SCALING_FAILURE = "auto_scaling_failure"
    UNKNOWN = "unknown"


class Severity(StrEnum):
    """Incident severity, used for both prioritization and remediation gating."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class TriggerSource(StrEnum):
    """Where an incident originated."""

    CLOUDWATCH_ALARM = "cloudwatch_alarm"
    GUARDDUTY_FINDING = "guardduty_finding"
    SCHEDULED_SCAN = "scheduled_scan"
    MANUAL = "manual"


class RemediationStatus(StrEnum):
    """Lifecycle states of a RemediationPlan."""

    NOT_STARTED = "not_started"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXECUTING = "executing"
    VERIFIED = "verified"
    FAILED = "failed"
    ESCALATED = "escalated"


class RemediationMode(StrEnum):
    """Global execution mode for the Remediation Executor's tool binding."""

    DRY_RUN = "dry_run"
    LIVE = "live"


class AgentName(StrEnum):
    """Canonical identifiers for each node in the LangGraph agent graph."""

    COORDINATOR = "coordinator"
    INFRASTRUCTURE = "infrastructure"
    MONITORING = "monitoring"
    TROUBLESHOOTING = "troubleshooting"
    SECURITY = "security"
    COST = "cost"
    DEPLOYMENT = "deployment"
    REMEDIATION_EXECUTOR = "remediation_executor"
