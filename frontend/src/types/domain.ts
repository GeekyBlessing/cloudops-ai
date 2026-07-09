/**
 * TypeScript mirror of the backend's domain models (backend/src/cloudops_ai/domain/).
 *
 * These types are hand-kept in sync with the Pydantic models they mirror --
 * there's no shared schema/codegen step yet (that would be a reasonable
 * follow-up, e.g. generating this file from FastAPI's OpenAPI schema). Until
 * then, any change to a backend model's fields needs a matching edit here.
 * Field names and casing match the backend exactly (snake_case, not
 * camelCase) since these types describe the JSON the API actually sends --
 * translating to camelCase would just be a second place for the two sides
 * to drift apart.
 */

// ---------------- Enums (domain/enums.py) ----------------

export type IncidentType =
  | "ec2_high_cpu"
  | "ec2_down"
  | "public_s3_bucket"
  | "iam_misconfiguration"
  | "high_billing"
  | "lambda_errors"
  | "rds_storage_full"
  | "auto_scaling_failure"
  | "unknown";

export type Severity = "low" | "medium" | "high" | "critical";

export type TriggerSource = "cloudwatch_alarm" | "guardduty_finding" | "scheduled_scan" | "manual";

export type RemediationStatus =
  | "not_started"
  | "awaiting_approval"
  | "approved"
  | "rejected"
  | "executing"
  | "verified"
  | "failed"
  | "escalated";

export type AgentName =
  | "coordinator"
  | "infrastructure"
  | "monitoring"
  | "troubleshooting"
  | "security"
  | "cost"
  | "deployment"
  | "remediation_executor";

// ---------------- domain/models/resource.py ----------------

export interface ResourceRef {
  arn: string;
  resource_type: string;
  region: string;
  account_id: string;
  name: string | null;
  tags: Record<string, string>;
  attributes: Record<string, unknown>;
  last_synced_at: string; // ISO 8601
}

// ---------------- domain/models/evidence.py ----------------

export interface Evidence {
  evidence_id: string;
  agent: AgentName;
  source: string;
  summary: string;
  data: Record<string, unknown>;
  collected_at: string; // ISO 8601
}

export interface AgentStep {
  step_id: string;
  agent: AgentName;
  started_at: string; // ISO 8601
  completed_at: string | null; // ISO 8601, null while the step is in flight
  reasoning: string;
  tool_calls: string[];
  evidence_ids: string[];
}

// ---------------- domain/models/remediation.py ----------------

export interface ApprovalToken {
  plan_id: string;
  approved_by: string;
  approved_at: string; // ISO 8601
  signature: string;
}

export interface RemediationAction {
  action_name: string;
  target_arn: string;
  parameters: Record<string, unknown>;
  is_reversible: boolean;
}

export interface RemediationPlan {
  plan_id: string;
  incident_id: string;
  actions: RemediationAction[];
  status: RemediationStatus;
  requires_approval: boolean;
  approval: ApprovalToken | null;
  rationale: string;
  created_at: string; // ISO 8601
}

// ---------------- domain/models/report.py ----------------
// Always null today -- IncidentReport generation isn't wired up yet -- but
// typed here so the dashboard doesn't need a follow-up change the day it is.

export interface TimelineEntry {
  timestamp: string; // ISO 8601
  label: string;
  detail: string;
}

export interface IncidentReport {
  incident_id: string;
  incident_type: IncidentType;
  severity: Severity;
  summary: string;
  root_cause: string;
  remediation_taken: string;
  remediation_status: RemediationStatus;
  supporting_evidence_ids: string[];
  timeline: TimelineEntry[];
  generated_at: string; // ISO 8601
  generated_by: string;
}

// ---------------- domain/models/incident.py ----------------

export interface IncidentState {
  incident_id: string;
  trigger_source: TriggerSource;
  incident_type: IncidentType;
  severity: Severity | null;
  affected_resources: ResourceRef[];
  evidence: Evidence[];
  agent_trace: AgentStep[];
  root_cause_hypothesis: string | null;
  proposed_remediation: RemediationPlan | null;
  remediation_status: RemediationStatus;
  report: IncidentReport | null;
  created_at: string; // ISO 8601
  updated_at: string; // ISO 8601
}

// ---------------- api/routers/incidents.py response/request shapes ----------------

/** Lightweight shape used by GET /incidents -- see IncidentSummary in the backend router. */
export interface IncidentSummary {
  incident_id: string;
  incident_type: IncidentType;
  severity: Severity | null;
  remediation_status: RemediationStatus;
  created_at: string; // ISO 8601
}

export interface CreateIncidentRequest {
  trigger_source?: TriggerSource;
  instance_arn: string;
}

// ---------------- api/routers/remediation.py request shapes ----------------

export interface ApprovalRequest {
  approved_by: string;
}
