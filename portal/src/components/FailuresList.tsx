import { useState } from "react";
import type { Failure } from "../types";

interface FailuresListProps {
  failures: Failure[];
  onRefresh: () => void;
}

export function FailuresList({ failures, onRefresh }: FailuresListProps) {
  const [selected, setSelected] = useState<string | null>(null);
  const [rca, setRca] = useState<string | null>(null);

  const handleSelect = async (id: string) => {
    setSelected(id);
    try {
      const r = await fetch(`/api/v1/failures/${id}/rca`);
      const d = await r.json();
      setRca(d.summary ?? d.error ?? "No RCA available.");
    } catch {
      setRca("Failed to load RCA.");
    }
  };

  return (
    <div className="failures-section">
      <div className="failures-header">
        <h2>Pipeline Failures</h2>
        <button className="btn-refresh" onClick={onRefresh}>
          Refresh
        </button>
      </div>
      {failures.length === 0 ? (
        <p className="empty-state">
          No failures recorded. Trigger a Jenkins or GitHub Actions failure,
          then call the webhook.
        </p>
      ) : (
        <div className="failures-layout">
          <ul className="failures-list">
            {failures.map((f) => (
              <li
                key={f.id}
                className={`failure-item ${selected === f.id ? "selected" : ""}`}
                onClick={() => handleSelect(f.id)}
              >
                <span className="source">{f.source}</span>
                {f.job_name && (
                  <span className="job">
                    {f.job_name} #{f.build_number}
                  </span>
                )}
                {f.repo && <span className="repo">{f.repo}</span>}
                <span className="time">
                  {new Date(f.triggered_at).toLocaleString()}
                </span>
                {f.rca_summary && <span className="badge">RCA ready</span>}
              </li>
            ))}
          </ul>
          <div className="rca-panel">
            {selected ? (
              <div className="rca-content">
                <h3>Root Cause Analysis</h3>
                <pre>{rca ?? "Loading…"}</pre>
              </div>
            ) : (
              <p className="rca-placeholder">Select a failure to view RCA</p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
