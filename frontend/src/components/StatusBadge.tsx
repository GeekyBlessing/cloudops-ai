/**
 * StatusBadge renders a small colored pill for a severity or remediation
 * status value. Colors are looked up from a fixed map rather than derived
 * from the string itself (e.g. hashing to a color) -- an operator scanning
 * a table of incidents needs "critical" to always render the same color,
 * every time, not a color that happens to fall out of a hash function.
 */

import type { RemediationStatus, Severity } from "../types/domain";

export type BadgeTone = "neutral" | "info" | "warning" | "danger" | "success";

const SEVERITY_TONES: Record<Severity, BadgeTone> = {
  low: "neutral",
  medium: "info",
  high: "warning",
  critical: "danger",
};

const STATUS_TONES: Record<RemediationStatus, BadgeTone> = {
  not_started: "neutral",
  awaiting_approval: "warning",
  approved: "info",
  rejected: "neutral",
  executing: "info",
  verified: "success",
  failed: "danger",
  escalated: "danger",
};

export function severityBadgeTone(severity: Severity | null): BadgeTone {
  return severity ? SEVERITY_TONES[severity] : "neutral";
}

export function statusBadgeTone(status: RemediationStatus): BadgeTone {
  return STATUS_TONES[status];
}

interface StatusBadgeProps {
  label: string;
  tone: BadgeTone;
}

export function StatusBadge({ label, tone }: StatusBadgeProps) {
  return <span className={`badge badge--${tone}`}>{label.replace(/_/g, " ")}</span>;
}
