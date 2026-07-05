import { WikiBrowser } from "../components/WikiBrowser";

export default function Wiki() {
  return (
    <div className="wiki-page">
      <h1>Knowledge Wiki</h1>
      <p className="lead">
        Git-backed, Markdown-native knowledge base. The agent writes here when it resolves a novel
        failure and reads it first before reasoning — so your team's accumulated know-how is always
        in the loop.
      </p>
      <WikiBrowser />
    </div>
  );
}
