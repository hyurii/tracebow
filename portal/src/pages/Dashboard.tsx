import { Link } from "react-router-dom";

export default function Dashboard() {
  return (
    <div className="dashboard-page">
      <h1>Welcome to Tracebow</h1>
      <p className="lead">
        Local, agent-driven root cause analysis for Jenkins, GitHub Actions, Jira, and Slack. Zero
        egress — your data stays within your infrastructure.
      </p>
      <div className="dashboard-cards">
        <Link to="/failures" className="card">
          <h3>Pipeline Failures</h3>
          <p>Recent failures, stack traces, and RCA summaries</p>
        </Link>
        <Link to="/chat" className="card">
          <h3>Agent Chat</h3>
          <p>Ask the AI agent to investigate, correlate, or search</p>
        </Link>
        <Link to="/wiki" className="card">
          <h3>Wiki</h3>
          <p>Browse the Git-backed knowledge base of resolutions & policies</p>
        </Link>
        <Link to="/settings" className="card">
          <h3>Settings</h3>
          <p>Configure integrations, tokens, and wiki backup</p>
        </Link>
      </div>
      <div className="dashboard-info">
        <h3>How it works</h3>
        <ul>
          <li>
            The Go CLI agent watches CI/CD jobs and POSTs failures to <code>/api/v1/analyze</code>.
            Jenkins & GitHub webhooks are also accepted at <code>/api/v1/webhooks/jenkins</code> and{" "}
            <code>/api/v1/webhooks/github</code>.
          </li>
          <li>
            A LangGraph orchestrator running on local Ollama models searches the wiki first, reasons
            over the stack trace, then writes back the resolution as a versioned Markdown file.
          </li>
          <li>
            Failures and RCA summaries are stored in Postgres. Long-term knowledge lives in the
            Git-backed wiki and can optionally be pushed to your own remote for backup.
          </li>
        </ul>
      </div>
    </div>
  );
}
