/**
 * Full incident detail view: affected resources, evidence, the agent audit
 * trail, and -- when a plan is awaiting approval -- the Approve/Reject
 * controls that call the /remediation endpoints. This page is the
 * human-in-the-loop safety gate made visible: nothing here can trigger an
 * AWS mutation without an explicit click here (or an equivalent direct API
 * call), and the backend enforces that independently of anything this page
 * does or doesn't render -- see backend/src/cloudops_ai/domain/models/remediation.py.
 */

import { useCallback, useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { ApiError, approveRemediation, getIncident, rejectRemediation } from "../api/client";
import { AgentTraceList } from "../components/AgentTraceList";
import { EvidenceList } from "../components/EvidenceList";
import { StatusBadge, severityBadgeTone, statusBadgeTone } from "../components/StatusBadge";
import type { IncidentState } from "../types/domain";

export function IncidentDetailPage() {
  const { incidentId } = useParams<{ incidentId: string }>();
  const [incident, setIncident] = useState<IncidentState | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [approverName, setApproverName] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  const refresh = useCallback(async () => {
    if (!incidentId) return;
    setIsLoading(true);
    setError(null);
    try {
      const data = await getIncident(incidentId);
      setIncident(data);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load incident.");
    } finally {
      setIsLoading(false);
    }
  }, [incidentId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function handleApprove() {
    if (!incidentId || !approverName.trim()) return;
    setIsSubmitting(true);
    setError(null);
    try {
      await approveRemediation(incidentId, approverName.trim());
      await refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to approve remediation.");
    } finally {
      setIsSubmitting(false);
    }
  }

  async function handleReject() {
    if (!incidentId) return;
    setIsSubmitting(true);
    setError(null);
    try {
      await rejectRemediation(incidentId);
      await refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to reject remediation.");
    } finally {
      setIsSubmitting(false);
    }
  }

  if (isLoading && !incident) {
    return <p>Loading...</p>;
  }

  if (error && !incident) {
    return <p className="error-banner">{error}</p>;
  }

  if (!incident) {
    return <p className="empty-state">Incident not found.</p>;
  }

  const plan = incident.proposed_remediation;
  const canDecide = plan !== null && plan.status === "awaiting_approval";

  return (
    <section>
      {error && <p className="error-banner">{error}</p>}

      <div className="panel">
        <div className="panel__header">
          <h2>{incident.incident_id}</h2>
          <button type="button" onClick={() => void refresh()} disabled={isLoading}>
            Refresh
          </button>
        </div>
        <div className="badge-row">
          <StatusBadge label={incident.incident_type} tone="neutral" />
          {incident.severity && (
            <StatusBadge label={incident.severity} tone={severityBadgeTone(incident.severity)} />
          )}
          <StatusBadge label={incident.remediation_status} tone={statusBadgeTone(incident.remediation_status)} />
        </div>
        <p>Trigger source: {incident.trigger_source.replace(/_/g, " ")}</p>
        <p>Created: {new Date(incident.created_at).toLocaleString()}</p>
        {incident.root_cause_hypothesis && (
          <p>
            <strong>Root cause hypothesis:</strong> {incident.root_cause_hypothesis}
          </p>
        )}
      </div>

      <div className="panel">
        <h3>Affected resources</h3>
        {incident.affected_resources.length === 0 ? (
          <p className="empty-state">None recorded.</p>
        ) : (
          <ul>
            {incident.affected_resources.map((resource) => (
              <li key={resource.arn}>
                <code>{resource.arn}</code> ({resource.resource_type})
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="panel">
        <h3>Proposed remediation</h3>
        {plan === null ? (
          <p className="empty-state">No remediation plan was proposed for this incident.</p>
        ) : (
          <div>
            <p>{plan.rationale}</p>
            <ul>
              {plan.actions.map((action) => (
                <li key={`${action.action_name}-${action.target_arn}`}>
                  <code>{action.action_name}</code> on <code>{action.target_arn}</code>
                  {action.is_reversible ? " (reversible)" : " (irreversible)"}
                </li>
              ))}
            </ul>
            <p>
              Status: <StatusBadge label={plan.status} tone={statusBadgeTone(plan.status)} />
            </p>
            {plan.approval && (
              <p className="muted">
                Approved by {plan.approval.approved_by} at {new Date(plan.approval.approved_at).toLocaleString()}
              </p>
            )}
            {canDecide && (
              <div className="approval-form">
                <label htmlFor="approver-name">Your name / email</label>
                <input
                  id="approver-name"
                  type="text"
                  value={approverName}
                  onChange={(event) => setApproverName(event.target.value)}
                  placeholder="you@example.com"
                />
                <div className="approval-form__actions">
                  <button
                    type="button"
                    onClick={() => void handleApprove()}
                    disabled={isSubmitting || !approverName.trim()}
                  >
                    Approve &amp; execute
                  </button>
                  <button
                    type="button"
                    className="button--danger"
                    onClick={() => void handleReject()}
                    disabled={isSubmitting}
                  >
                    Reject
                  </button>
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      <div className="panel">
        <h3>Evidence</h3>
        <EvidenceList evidence={incident.evidence} />
      </div>

      <div className="panel">
        <h3>Agent trace</h3>
        <AgentTraceList steps={incident.agent_trace} />
      </div>
    </section>
  );
}
