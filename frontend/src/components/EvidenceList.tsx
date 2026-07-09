/**
 * Renders the incident's evidence trail. Each entry is collapsible -- the
 * one-sentence summary is always visible (that's what a human scanning the
 * page actually needs), and the raw `data` payload (full CloudWatch
 * datapoints, CloudTrail events, etc.) is tucked behind a toggle so the
 * page isn't overwhelmed by raw JSON by default.
 */

import { useState } from "react";
import type { Evidence } from "../types/domain";

interface EvidenceListProps {
  evidence: Evidence[];
}

export function EvidenceList({ evidence }: EvidenceListProps) {
  if (evidence.length === 0) {
    return <p className="empty-state">No evidence collected yet.</p>;
  }

  return (
    <ul className="evidence-list">
      {evidence.map((item) => (
        <EvidenceItem key={item.evidence_id} item={item} />
      ))}
    </ul>
  );
}

function EvidenceItem({ item }: { item: Evidence }) {
  const [showRaw, setShowRaw] = useState(false);

  return (
    <li className="evidence-item">
      <div className="evidence-item__header">
        <span className="tag">{item.agent}</span>
        <span className="evidence-item__source">{item.source}</span>
        <span className="evidence-item__timestamp">{new Date(item.collected_at).toLocaleString()}</span>
      </div>
      <p className="evidence-item__summary">{item.summary}</p>
      <button type="button" className="link-button" onClick={() => setShowRaw((value) => !value)}>
        {showRaw ? "Hide raw data" : "Show raw data"}
      </button>
      {showRaw && <pre className="raw-block">{JSON.stringify(item.data, null, 2)}</pre>}
    </li>
  );
}
