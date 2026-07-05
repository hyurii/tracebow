import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import type { AccessRequest } from "../types";

export default function Access() {
  const [requests, setRequests] = useState<AccessRequest[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const data = await api.listAccessRequests();
      setRequests(data.requests);
      setError(null);
    } catch (err) {
      setError(String((err as Error).message ?? err));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const resolve = async (id: string, decision: "approved" | "denied") => {
    setBusy(id);
    try {
      await api.resolveAccessRequest(id, decision);
      await load();
    } catch (err) {
      setError(String((err as Error).message ?? err));
    } finally {
      setBusy(null);
    }
  };

  const pending = requests.filter((r) => r.status === "pending");
  const resolved = requests.filter((r) => r.status !== "pending");

  return (
    <div className="access-page">
      <h1>Access requests</h1>
      <p className="lead">
        When the agent needs data from a source it cannot reach, it opens a
        request here instead of accessing it silently. Approving one grants the
        repository outbound access.
      </p>
      {error && <p className="wiki-error">{error}</p>}

      <h2>Pending</h2>
      {pending.length === 0 ? (
        <p className="empty-state">No pending requests.</p>
      ) : (
        <div className="access-list">
          {pending.map((r) => (
            <div key={r.id} className="access-card">
              <div className="access-card-head">
                <span className="source">{r.provider}</span>
                <span className="repo-id">{r.identifier}</span>
                <span className="access-by">by {r.requested_by}</span>
              </div>
              {r.reason && <p className="access-reason">{r.reason}</p>}
              <div className="backup-actions">
                <button
                  disabled={busy === r.id}
                  onClick={() => void resolve(r.id, "approved")}
                >
                  Approve
                </button>
                <button
                  className="btn-secondary"
                  disabled={busy === r.id}
                  onClick={() => void resolve(r.id, "denied")}
                >
                  Deny
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {resolved.length > 0 && (
        <>
          <h2>History</h2>
          <table className="data-table">
            <thead>
              <tr>
                <th>Provider</th>
                <th>Identifier</th>
                <th>Status</th>
                <th>Resolved</th>
              </tr>
            </thead>
            <tbody>
              {resolved.map((r) => (
                <tr key={r.id}>
                  <td>{r.provider}</td>
                  <td>{r.identifier}</td>
                  <td>
                    <span className={`status-badge ${r.status}`}>
                      {r.status}
                    </span>
                  </td>
                  <td>
                    {r.resolved_at
                      ? new Date(r.resolved_at).toLocaleString()
                      : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </div>
  );
}
