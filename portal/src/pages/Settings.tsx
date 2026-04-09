export default function Settings() {
  return (
    <div className="settings-page">
      <h1>Configuration</h1>
      <p className="settings-desc">
        Configure API tokens and ingestion parameters for connected tools. All data stays local—zero egress.
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
          envVars={["JIRA_URL", "JIRA_EMAIL", "JIRA_API_TOKEN"]}
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
