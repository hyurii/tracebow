import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import type { EgressEvent, SecuritySummary } from "../types";

export default function Security() {
  const [summary, setSummary] = useState<SecuritySummary | null>(null);
  const [events, setEvents] = useState<EgressEvent[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [onlyExternal, setOnlyExternal] = useState(false);
  const [onlySensitive, setOnlySensitive] = useState(false);

  const load = useCallback(async () => {
    try {
      const [s, e] = await Promise.all([
        api.getSecuritySummary(),
        api.listEgressEvents({
          kind: onlyExternal ? "external" : undefined,
          sensitive: onlySensitive,
        }),
      ]);
      setSummary(s);
      setEvents(e.events);
      setError(null);
    } catch (err) {
      setError(String((err as Error).message ?? err));
    }
  }, [onlyExternal, onlySensitive]);

  useEffect(() => {
    void load();
  }, [load]);

  const internalOnly = summary?.posture === "internal_only";

  return (
    <div className="security-page">
      <h1>Security &amp; egress</h1>
      <p className="lead">
        Tracebow is designed to keep your data in-network. This page shows every
        outbound network attempt it has made, classified as internal
        infrastructure or genuinely external. It is an audit view — enforcement
        (a network firewall) still belongs to your deployment.
      </p>
      {error && <p className="wiki-error">{error}</p>}

      {summary && (
        <>
          <div
            className={`posture-banner ${internalOnly ? "ok" : "warn"}`}
            role="status"
          >
            {internalOnly ? (
              <>
                <strong>No external egress.</strong> All traffic stayed on your
                local stack (Ollama, Postgres, Redis).
              </>
            ) : (
              <>
                <strong>External integrations configured.</strong> Tracebow may
                contact: {summary.external_integrations.join(", ") || "—"}.
              </>
            )}
          </div>

          <div className="dashboard-cards">
            <StatCard label="Total calls" value={summary.total_events} />
            <StatCard label="Internal" value={summary.internal_events} />
            <StatCard
              label="External"
              value={summary.external_events}
              tone={summary.external_events > 0 ? "warn" : undefined}
            />
            <StatCard
              label="Sensitive flagged"
              value={summary.sensitive_events}
              tone={summary.sensitive_events > 0 ? "error" : undefined}
            />
          </div>

          <h2>Destinations</h2>
          {summary.destinations.length === 0 ? (
            <p className="empty-state">No outbound calls recorded yet.</p>
          ) : (
            <table className="data-table">
              <thead>
                <tr>
                  <th>Host</th>
                  <th>Kind</th>
                  <th>Calls</th>
                  <th>Last seen</th>
                </tr>
              </thead>
              <tbody>
                {summary.destinations.map((d) => (
                  <tr key={`${d.host}-${d.kind}`}>
                    <td>
                      <code>{d.host}</code>
                    </td>
                    <td>
                      <span className={`status-badge ${d.kind}`}>{d.kind}</span>
                    </td>
                    <td>{d.count}</td>
                    <td>
                      {d.last_seen
                        ? new Date(d.last_seen).toLocaleString()
                        : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </>
      )}

      <h2>Recent egress events</h2>
      <div className="egress-filters">
        <label className="backup-field-inline">
          <input
            type="checkbox"
            checked={onlyExternal}
            onChange={(e) => setOnlyExternal(e.target.checked)}
          />
          External only
        </label>
        <label className="backup-field-inline">
          <input
            type="checkbox"
            checked={onlySensitive}
            onChange={(e) => setOnlySensitive(e.target.checked)}
          />
          Sensitive only
        </label>
        <button className="btn-secondary" onClick={() => void load()}>
          Refresh
        </button>
      </div>

      {events.length === 0 ? (
        <p className="empty-state">No events match the current filter.</p>
      ) : (
        <table className="data-table">
          <thead>
            <tr>
              <th>Time</th>
              <th>Host</th>
              <th>Kind</th>
              <th>Purpose</th>
              <th>Status</th>
              <th>Sensitive</th>
            </tr>
          </thead>
          <tbody>
            {events.map((ev) => (
              <tr key={ev.id} className={ev.blocked ? "row-blocked" : ""}>
                <td>
                  {ev.created_at
                    ? new Date(ev.created_at).toLocaleTimeString()
                    : "—"}
                </td>
                <td>
                  <code>{ev.destination_host}</code>
                </td>
                <td>
                  <span className={`status-badge ${ev.destination_kind}`}>
                    {ev.destination_kind}
                  </span>
                </td>
                <td>{ev.purpose ?? "—"}</td>
                <td>{ev.status ?? "—"}</td>
                <td>
                  {ev.sensitive_flags.length > 0 ? (
                    <span className="status-badge denied">
                      {ev.sensitive_flags.join(", ")}
                    </span>
                  ) : (
                    "—"
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function StatCard({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone?: "warn" | "error";
}) {
  return (
    <div className={`card stat-card ${tone ?? ""}`}>
      <h3>{value}</h3>
      <p>{label}</p>
    </div>
  );
}
