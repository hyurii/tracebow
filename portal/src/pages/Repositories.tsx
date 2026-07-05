import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import type { Repository, RepositoryUpdate } from "../types";

const AUTH_METHODS: Array<{
  value: Repository["auth_method"];
  label: string;
  supported: boolean;
}> = [
  { value: "none", label: "None", supported: true },
  { value: "github_pat", label: "GitHub token (PAT)", supported: true },
  { value: "ssh_deploy_key", label: "SSH deploy key", supported: true },
  { value: "github_app", label: "GitHub App (soon)", supported: false },
  { value: "oauth", label: "OAuth (soon)", supported: false },
];

export default function Repositories() {
  const [repos, setRepos] = useState<Repository[]>([]);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const data = await api.listRepositories();
      setRepos(data.repositories);
      setError(null);
    } catch (err) {
      setError(String((err as Error).message ?? err));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <div className="repos-page">
      <h1>Repositories</h1>
      <p className="lead">
        Every source that has sent Tracebow a failure. Ingress is always
        accepted; below you control whether the agent may reach{" "}
        <em>back out</em> to a source (to fetch diffs, PRs, or builds). New
        sources start as <strong>pending</strong> until you allow them.
      </p>
      {error && <p className="wiki-error">{error}</p>}
      {repos.length === 0 ? (
        <p className="empty-state">
          No repositories yet. They appear here after the first failure arrives.
        </p>
      ) : (
        <div className="repo-list">
          {repos.map((r) => (
            <RepoCard key={r.id} repo={r} onSaved={load} />
          ))}
        </div>
      )}
    </div>
  );
}

function RepoCard({
  repo,
  onSaved,
}: {
  repo: Repository;
  onSaved: () => void;
}) {
  const [authMethod, setAuthMethod] = useState(repo.auth_method);
  const [credential, setCredential] = useState("");
  const [rotate, setRotate] = useState(false);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const patch = async (update: RepositoryUpdate) => {
    setBusy(true);
    setErr(null);
    setMsg(null);
    try {
      await api.updateRepository(repo.id, update);
      setMsg("Saved.");
      onSaved();
    } catch (e) {
      setErr(String((e as Error).message ?? e));
    } finally {
      setBusy(false);
    }
  };

  const saveCredentials = () => {
    const update: RepositoryUpdate = { auth_method: authMethod };
    if (authMethod === "none") {
      update.credential = null;
    } else if (rotate) {
      update.credential = credential.trim() || null;
    }
    void patch(update).then(() => {
      setCredential("");
      setRotate(false);
    });
  };

  return (
    <div className="repo-card">
      <div className="repo-card-head">
        <div>
          <span className="source">{repo.provider}</span>
          <span className="repo-id">{repo.identifier}</span>
        </div>
        <span className={`status-badge ${repo.access_status}`}>
          {repo.access_status}
        </span>
      </div>

      <div className="repo-actions">
        <button
          className="btn-secondary"
          disabled={busy || repo.access_status === "allowed"}
          onClick={() => void patch({ access_status: "allowed" })}
        >
          Allow
        </button>
        <button
          className="btn-secondary"
          disabled={busy || repo.access_status === "denied"}
          onClick={() => void patch({ access_status: "denied" })}
        >
          Deny
        </button>
        <button
          className="btn-secondary"
          disabled={busy || repo.access_status === "pending"}
          onClick={() => void patch({ access_status: "pending" })}
        >
          Reset
        </button>
      </div>

      <div className="repo-creds">
        <label className="backup-field">
          Auth method
          <select
            value={authMethod}
            onChange={(e) =>
              setAuthMethod(e.target.value as Repository["auth_method"])
            }
          >
            {AUTH_METHODS.map((m) => (
              <option key={m.value} value={m.value} disabled={!m.supported}>
                {m.label}
              </option>
            ))}
          </select>
        </label>

        <div className="repo-cred-status">
          {repo.has_credential ? (
            <>
              <strong>Credential on file.</strong>{" "}
              {repo.credential_fingerprint && (
                <code>{repo.credential_fingerprint}</code>
              )}
            </>
          ) : (
            <em>No credential stored.</em>
          )}
        </div>

        {authMethod !== "none" && (
          <label className="backup-field-inline">
            <input
              type="checkbox"
              checked={rotate}
              onChange={(e) => setRotate(e.target.checked)}
            />
            {repo.has_credential ? "Replace credential" : "Add credential"}
          </label>
        )}

        {authMethod !== "none" && rotate && (
          <label className="backup-field">
            {authMethod === "github_pat"
              ? "GitHub token"
              : "SSH private key (PEM)"}
            {authMethod === "github_pat" ? (
              <input
                type="password"
                value={credential}
                onChange={(e) => setCredential(e.target.value)}
                placeholder="ghp_..."
              />
            ) : (
              <textarea
                value={credential}
                onChange={(e) => setCredential(e.target.value)}
                rows={6}
                placeholder="Paste the SSH private key"
              />
            )}
            <small className="backup-hint">
              Stored encrypted at rest; never shown again.
            </small>
          </label>
        )}

        <div className="backup-actions">
          <button disabled={busy} onClick={saveCredentials}>
            Save credentials
          </button>
        </div>
        {err && <p className="wiki-error">{err}</p>}
        {msg && <p className="backup-flash">{msg}</p>}
      </div>
    </div>
  );
}
