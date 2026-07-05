import { useEffect, useState } from "react";
import { api } from "../api";
import type { BackupSettings } from "../types";

export default function Settings() {
  return (
    <div className="settings-page">
      <h1>Configuration</h1>
      <p className="settings-desc">
        All data stays local — zero egress. Integrations below are read-only references to
        environment variables. The backup section below is managed at runtime through this UI.
      </p>

      <section className="settings-section">
        <h2>Integrations</h2>
        <p className="settings-desc">
          Set these in <code>.env</code> or in your deployment environment.
        </p>
        <div className="settings-grid">
          <SettingCard
            title="Jenkins"
            description="Base URL and API token for Jenkins controller"
            envVars={["JENKINS_URL", "JENKINS_USER", "JENKINS_API_TOKEN"]}
          />
          <SettingCard
            title="GitHub"
            description="Personal access token for repos and workflows, plus webhook secret"
            envVars={["GITHUB_TOKEN", "GITHUB_WEBHOOK_SECRET"]}
          />
          <SettingCard
            title="Jira"
            description="Atlassian API token for JQL search"
            envVars={["JIRA_URL", "JIRA_EMAIL", "JIRA_API_TOKEN"]}
          />
          <SettingCard
            title="Slack"
            description="Bot token and signing secret for channel history and threads"
            envVars={["SLACK_BOT_TOKEN", "SLACK_SIGNING_SECRET"]}
          />
        </div>
      </section>

      <BackupSection />
    </div>
  );
}

function SettingCard({
  title,
  description,
  envVars,
}: {
  title: string;
  description: string;
  envVars: string[];
}) {
  return (
    <div className="setting-card">
      <h3>{title}</h3>
      <p>{description}</p>
      <ul>
        {envVars.map((v) => (
          <li key={v}>
            <code>{v}</code>
          </li>
        ))}
      </ul>
    </div>
  );
}

function BackupSection() {
  const [settings, setSettings] = useState<BackupSettings | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [flash, setFlash] = useState<string | null>(null);

  const [enabled, setEnabled] = useState(false);
  const [remoteUrl, setRemoteUrl] = useState("");
  const [branch, setBranch] = useState("main");
  const [autoBackupHours, setAutoBackupHours] = useState<string>("24");
  const [deployKey, setDeployKey] = useState("");
  const [rotateKey, setRotateKey] = useState(false);

  const load = async () => {
    try {
      const s = await api.getBackupSettings();
      setSettings(s);
      setEnabled(s.enabled);
      setRemoteUrl(s.remote_url ?? "");
      setBranch(s.branch ?? "main");
      setAutoBackupHours(s.auto_backup_hours != null ? String(s.auto_backup_hours) : "");
    } catch (err) {
      setLoadError(String((err as Error).message ?? err));
    }
  };

  useEffect(() => {
    void load();
  }, []);

  const save = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setSaveError(null);
    setFlash(null);
    try {
      const body: Parameters<typeof api.saveBackupSettings>[0] = {
        enabled,
        remote_url: remoteUrl.trim() || null,
        branch: branch.trim() || "main",
        auto_backup_hours: autoBackupHours.trim() ? Number(autoBackupHours) : null,
      };
      if (rotateKey && deployKey.trim()) {
        body.deploy_key = deployKey;
      } else if (rotateKey && !deployKey.trim()) {
        body.deploy_key = null;
      }
      const updated = await api.saveBackupSettings(body);
      setSettings(updated);
      setFlash("Saved.");
      setDeployKey("");
      setRotateKey(false);
    } catch (err) {
      setSaveError(String((err as Error).message ?? err));
    } finally {
      setSaving(false);
    }
  };

  const triggerBackup = async () => {
    setFlash(null);
    setSaveError(null);
    try {
      await api.triggerBackup();
      setFlash("Backup queued.");
    } catch (err) {
      setSaveError(String((err as Error).message ?? err));
    }
  };

  return (
    <section className="settings-section">
      <h2>Wiki backup</h2>
      <p className="settings-desc">
        Optionally push the Git-backed wiki to <strong>any</strong> Git remote over SSH — GitHub,
        GitLab, Gitea, Bitbucket, or self-hosted Git. Tracebow never makes outbound calls unless you
        configure this. The deploy key is encrypted at rest with <code>WIKI_SECRET_KEY</code> and is
        never displayed again after you save it.
      </p>
      {loadError && <p className="wiki-error">Could not load: {loadError}</p>}
      {settings && (
        <form className="backup-form" onSubmit={save}>
          <label className="backup-field-inline">
            <input
              type="checkbox"
              checked={enabled}
              onChange={(e) => setEnabled(e.target.checked)}
            />
            Enable backup
          </label>

          <label className="backup-field">
            Remote URL
            <input
              type="text"
              value={remoteUrl}
              placeholder="git@github.com:your-org/tracebow-wiki.git, git@gitlab.example.com:..."
              onChange={(e) => setRemoteUrl(e.target.value)}
            />
            <span className="backup-hint">
              Any SSH Git URL is accepted (GitHub, GitLab, Gitea, Bitbucket, self-hosted).
            </span>
          </label>

          <label className="backup-field">
            Branch
            <input type="text" value={branch} onChange={(e) => setBranch(e.target.value)} />
          </label>

          <label className="backup-field">
            Auto-backup every N hours (blank = disabled)
            <input
              type="number"
              min="1"
              value={autoBackupHours}
              onChange={(e) => setAutoBackupHours(e.target.value)}
            />
          </label>

          <div className="backup-deploy-key">
            <div className="backup-deploy-key-status">
              {settings.has_deploy_key ? (
                <>
                  <strong>Deploy key on file.</strong>{" "}
                  {settings.deploy_key_fingerprint && (
                    <code>{settings.deploy_key_fingerprint}</code>
                  )}
                </>
              ) : (
                <em>No deploy key stored.</em>
              )}
            </div>
            <label className="backup-field-inline">
              <input
                type="checkbox"
                checked={rotateKey}
                onChange={(e) => setRotateKey(e.target.checked)}
              />
              {settings.has_deploy_key ? "Replace deploy key" : "Add deploy key"}
            </label>
            {rotateKey && (
              <label className="backup-field">
                Private key (PEM)
                <textarea
                  value={deployKey}
                  onChange={(e) => setDeployKey(e.target.value)}
                  placeholder={"Paste your SSH private key (PEM/OpenSSH)"}
                  rows={8}
                />
                <small className="backup-hint">
                  The key is sent once and stored encrypted. It will never be shown again.
                </small>
              </label>
            )}
          </div>

          {settings.last_backup_at && (
            <p className="backup-last">
              Last run: {new Date(settings.last_backup_at).toLocaleString()} —{" "}
              <strong>{settings.last_backup_status ?? "unknown"}</strong>
              {settings.last_backup_error && (
                <>
                  <br />
                  <span className="wiki-error">{settings.last_backup_error}</span>
                </>
              )}
            </p>
          )}

          {saveError && <p className="wiki-error">{saveError}</p>}
          {flash && <p className="backup-flash">{flash}</p>}

          <div className="backup-actions">
            <button type="submit" disabled={saving}>
              {saving ? "Saving…" : "Save"}
            </button>
            <button
              type="button"
              className="btn-secondary"
              onClick={triggerBackup}
              disabled={!settings.has_deploy_key || !settings.remote_url}
              title={
                !settings.has_deploy_key || !settings.remote_url
                  ? "Configure remote URL and deploy key first"
                  : "Queue a backup right now"
              }
            >
              Backup now
            </button>
          </div>
        </form>
      )}
    </section>
  );
}
