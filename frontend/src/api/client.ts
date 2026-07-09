/**
 * Typed fetch wrapper around the CloudOps AI backend API.
 *
 * Every function here corresponds to exactly one backend route (see
 * backend/src/cloudops_ai/api/routers/) -- this module is the *only* place
 * in the frontend that knows the API's base URL, request/response shapes,
 * or how errors are formatted. Components never call `fetch` directly.
 */

import type {
  ApprovalRequest,
  CreateIncidentRequest,
  IncidentState,
  IncidentSummary,
} from "../types/domain";

// Falls back to the local dev backend if VITE_API_BASE_URL isn't set --
// matches the default port uvicorn uses in every terminal command in the
// backend README. Override via a .env.local file (see .env.example).
const API_BASE_URL: string = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

/**
 * Raised for any non-2xx response. Carries the HTTP status and, when the
 * backend returned FastAPI's standard `{"detail": "..."}` error shape, that
 * detail message -- which is usually specific enough to show directly in
 * the UI (e.g. "Plan status is 'verified', not 'awaiting_approval'").
 */
export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, detail: string) {
    super(detail);
    this.name = "ApiError";
    this.status = status;
  }
}

async function request<TResponse>(path: string, init?: RequestInit): Promise<TResponse> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });

  if (!response.ok) {
    let detail = response.statusText || `Request failed with status ${response.status}`;
    try {
      const body: unknown = await response.json();
      if (body && typeof body === "object" && "detail" in body && typeof body.detail === "string") {
        detail = body.detail;
      }
    } catch {
      // Response body wasn't JSON (or was empty) -- fall back to statusText.
    }
    throw new ApiError(response.status, detail);
  }

  // 200s with no body (none currently, but defensive) would fail response.json();
  // every endpoint this client calls always returns a JSON body, so this is safe.
  return (await response.json()) as TResponse;
}

/** GET /incidents -- the incident queue, most recent first. */
export function listIncidents(): Promise<IncidentSummary[]> {
  return request<IncidentSummary[]>("/incidents");
}

/** GET /incidents/{id} -- full incident detail, including evidence and agent_trace. */
export function getIncident(incidentId: string): Promise<IncidentState> {
  return request<IncidentState>(`/incidents/${encodeURIComponent(incidentId)}`);
}

/** POST /incidents -- creates an incident and synchronously runs it through the agent graph. */
export function createIncident(payload: CreateIncidentRequest): Promise<IncidentState> {
  return request<IncidentState>("/incidents", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

/** POST /remediation/{id}/approve -- signs an approval and executes the plan. */
export function approveRemediation(incidentId: string, approvedBy: string): Promise<IncidentState> {
  const payload: ApprovalRequest = { approved_by: approvedBy };
  return request<IncidentState>(`/remediation/${encodeURIComponent(incidentId)}/approve`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

/** POST /remediation/{id}/reject -- marks the plan rejected. No AWS call is made. */
export function rejectRemediation(incidentId: string): Promise<IncidentState> {
  return request<IncidentState>(`/remediation/${encodeURIComponent(incidentId)}/reject`, {
    method: "POST",
  });
}
