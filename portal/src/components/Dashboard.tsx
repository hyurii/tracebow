import { useState, useEffect } from "react";
import { FailuresList } from "./FailuresList";
import { ChatInterface } from "./ChatInterface";
import type { Failure } from "../types";

type Tab = "failures" | "chat" | "settings";

export function Dashboard() {
  const [activeTab, setActiveTab] = useState<Tab>("failures");
  const [failures, setFailures] = useState<Failure[]>([]);

  useEffect(() => {
    fetch("/api/v1/failures")
      .then((r) => r.json())
      .then((d) => setFailures(d.failures ?? []))
      .catch(() => setFailures([]));
  }, []);

  return (
    <div className="dashboard">
      <header className="header">
        <h1 className="logo">
          <span className="logo-icon">⟡</span> Tracebow
        </h1>
        <p className="tagline">Local AI Root Cause Analysis for CI/CD</p>
        <nav className="tabs">
          <button
            className={activeTab === "failures" ? "active" : ""}
            onClick={() => setActiveTab("failures")}
          >
            Pipeline Failures
          </button>
          <button
            className={activeTab === "chat" ? "active" : ""}
            onClick={() => setActiveTab("chat")}
          >
            Agent Chat
          </button>
          <button
            className={activeTab === "settings" ? "active" : ""}
            onClick={() => setActiveTab("settings")}
          >
            Settings
          </button>
        </nav>
      </header>

      <main className="content">
        {activeTab === "failures" && (
          <FailuresList failures={failures} onRefresh={() => window.location.reload()} />
        )}
        {activeTab === "chat" && <ChatInterface />}
        {activeTab === "settings" && <SettingsPanel />}
      </main>
    </div>
  );
}

function SettingsPanel() {
  return (
    <div className="settings-panel">
      <h2>Configuration</h2>
      <p className="settings-desc">
        Configure API tokens and ingestion parameters for connected tools. All data stays local—zero
        egress.
      </p>
      <div className="settings-grid">
        <SettingCard
          title="Jenkins"
          description="Base URL and API token for Jenkins controller"
          envVars={["JENKINS_URL", "JENKINS_API_TOKEN"]}
        />
        <SettingCard
          title="GitHub"
          description="Personal access token for repos and workflows"
          envVars={["GITHUB_TOKEN"]}
        />
        <SettingCard
          title="Jira"
          description="Atlassian API token for JQL search"
          envVars={["JIRA_BASE_URL", "JIRA_EMAIL", "JIRA_API_TOKEN"]}
        />
        <SettingCard
          title="Slack"
          description="Bot token for channel history and threads"
          envVars={["SLACK_BOT_TOKEN"]}
        />
      </div>
      <p className="settings-footer">
        Set these variables in <code>.env</code> or your deployment environment.
      </p>
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
