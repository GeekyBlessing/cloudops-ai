/**
 * Landing page: the incident queue. Also doubles as the manual "create an
 * incident" form -- there's no EventBridge/CloudWatch Alarm trigger wired
 * up yet (see /docs/ARCHITECTURE.md), so this form is how a new incident
 * enters the system during local development or a demo.
 */

import { useEffect, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { ApiError, createIncident, listIncidents } from "../api/client";
import { StatusBadge, severityBadgeTone, statusBadgeTone } from "../components/StatusBadge";
import type { IncidentSummary } from "../types/domain";

const DEFAULT_INSTANCE_ARN = "arn:aws:ec2:us-east-1:123456789012:instance/i-0abcd1234";

export function IncidentListPage() {
  const [incidents, setIncidents] = useState<IncidentSummary[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [instanceArn, setInstanceArn] = useState(DEFAULT_INSTANCE_ARN);
  const [isCreating, setIsCreating] = useState(false);

  async function refresh() {
    setIsLoading(true);
    setError(null);
    try {
      const data = await listIncidents();
      setIncidents(data);
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.isAuthError
            ? `${err.message} -- set it via the "API key" control in the header above.`
            : err.message
          : "Failed to load incidents.",
      );
    } finally {
      setIsLoading(false);
    }
  }

  useEffect(() => {
    void refresh();
  }, []);

  async function handleCreate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setIsCreating(true);
    setError(null);
    try {
      // Runs synchronously through the full agent graph server-side
      // (classify -> specialist -> decide) -- this can take a few seconds,
      // which is why the button switches to a "running" label rather than
      // just disabling silently.
      await createIncident({ instance_arn: instanceArn });
      await refresh();
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.isAuthError
            ? `${err.message} -- set it via the "API key" control in the header above.`
            : err.message
          : "Failed to create incident.",
      );
    } finally {
      setIsCreating(false);
    }
  }

  return (
    <section>
      <div className="panel">
        <h2>New incident</h2>
        <form className="stacked-form" onSubmit={handleCreate}>
          <label htmlFor="instance-arn">EC2 instance ARN</label>
          <input
            id="instance-arn"
            type="text"
            value={instanceArn}
            onChange={(event) => setInstanceArn(event.target.value)}
            required
          />
          <button type="submit" disabled={isCreating}>
            {isCreating ? "Running agent graph..." : "Create incident"}
          </button>
        </form>
      </div>

      {error && <p className="error-banner">{error}</p>}

      <div className="panel">
        <div className="panel__header">
          <h2>Incidents</h2>
          <button type="button" onClick={() => void refresh()} disabled={isLoading}>
            Refresh
          </button>
        </div>

        {isLoading ? (
          <p>Loading...</p>
        ) : incidents.length === 0 ? (
          <p className="empty-state">No incidents yet -- create one above.</p>
        ) : (
          <table className="incident-table">
            <thead>
              <tr>
                <th>Incident</th>
                <th>Type</th>
                <th>Severity</th>
                <th>Status</th>
                <th>Created</th>
              </tr>
            </thead>
            <tbody>
              {incidents.map((incident) => (
                <tr key={incident.incident_id}>
                  <td>
                    <Link to={`/incidents/${incident.incident_id}`}>{incident.incident_id.slice(0, 8)}</Link>
                  </td>
                  <td>{incident.incident_type.replace(/_/g, " ")}</td>
                  <td>
                    {incident.severity && (
                      <StatusBadge label={incident.severity} tone={severityBadgeTone(incident.severity)} />
                    )}
                  </td>
                  <td>
                    <StatusBadge
                      label={incident.remediation_status}
                      tone={statusBadgeTone(incident.remediation_status)}
                    />
                  </td>
                  <td>{new Date(incident.created_at).toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </section>
  );
}
