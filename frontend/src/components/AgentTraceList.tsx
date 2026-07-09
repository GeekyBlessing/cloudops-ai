/**
 * Renders the incident's full audit trail -- every agent that ran, in
 * order, with its reasoning. This is the human-readable answer to "why did
 * the system do that?" that the backend's append-only IncidentState design
 * exists to support (see backend/src/cloudops_ai/domain/models/incident.py).
 */

import type { AgentStep } from "../types/domain";

interface AgentTraceListProps {
  steps: AgentStep[];
}

export function AgentTraceList({ steps }: AgentTraceListProps) {
  if (steps.length === 0) {
    return <p className="empty-state">No agent activity recorded yet.</p>;
  }

  return (
    <ol className="agent-trace">
      {steps.map((step) => (
        <li key={step.step_id} className="agent-trace__step">
          <div className="agent-trace__header">
            <span className="tag">{step.agent}</span>
            <span className="agent-trace__timestamp">{new Date(step.started_at).toLocaleString()}</span>
          </div>
          <p className="agent-trace__reasoning">{step.reasoning}</p>
          {step.tool_calls.length > 0 && (
            <p className="agent-trace__tools">Tools called: {step.tool_calls.join(", ")}</p>
          )}
        </li>
      ))}
    </ol>
  );
}
