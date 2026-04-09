import { Link } from "react-router-dom";

export default function Dashboard() {
  return (
    <div className="dashboard-page">
      <h1>Welcome to Tracebow</h1>
      <p className="lead">
        Local, agent-driven root cause analysis for Jenkins, GitHub Actions, Jira, and Slack.
        Zero egress—your data stays within your infrastructure.
      </p>
      <div className="dashboard-cards">
        <Link to="/failures" className="card">
          <h3>Pipeline Failures</h3>
          <p>View recent failures and RCA results</p>
        </Link>
        <Link to="/chat" className="card">
          <h3>Agent Chat</h3>
          <p>Ask the AI agent to investigate, correlate, or search</p>
        </Link>
        <Link to="/settings" className="card">
          <h3>Settings</h3>
          <p>Configure integrations and API tokens</p>
        </Link>
      </div>
      <div className="dashboard-info">
        <h3>Quick Start</h3>
        <ul>
          <li>Configure Jenkins/GitHub webhooks to POST failures to <code>/api/v1/webhooks/jenkins</code> or <code>/api/v1/webhooks/github</code></li>
          <li>Run ingestion to populate the vector and graph databases</li>
          <li>Use the chat interface to query across logs, Jira, and Slack</li>
        </ul>
      </div>
    </div>
  );
}
