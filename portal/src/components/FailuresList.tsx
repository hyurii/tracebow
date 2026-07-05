import { useState } from "react";
import DOMPurify from "dompurify";
import MarkdownIt from "markdown-it";
import { api } from "../api";
import type { CommitDiff, Failure, FailureDetail, Stacktrace } from "../types";

interface FailuresListProps {
  failures: Failure[];
  onRefresh: () => void;
}

const md = new MarkdownIt({ html: false, linkify: true, breaks: false });

export function FailuresList({ failures, onRefresh }: FailuresListProps) {
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<FailureDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const handleSelect = async (id: string) => {
    setSelected(id);
    setError(null);
    setDetail(null);
    setLoading(true);
    try {
      const d = await api.getFailure(id, true);
      setDetail(d);
    } catch (err) {
      setError(String((err as Error).message ?? err));
    } finally {
      setLoading(false);
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
          No failures recorded. Trigger a Jenkins or GitHub Actions failure, then call the webhook
          or run the CLI agent.
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
                    {f.job_name}
                    {f.build_number != null ? ` #${f.build_number}` : ""}
                  </span>
                )}
                {f.repo && <span className="repo">{f.repo}</span>}
                <span className="time">
                  {f.triggered_at ? new Date(f.triggered_at).toLocaleString() : "—"}
                </span>
                {f.rca_summary && <span className="badge">RCA ready</span>}
              </li>
            ))}
          </ul>
          <div className="rca-panel">
            {loading && <p>Loading…</p>}
            {error && <p className="wiki-error">{error}</p>}
            {!selected && !loading && !error && (
              <p className="rca-placeholder">Select a failure to view RCA</p>
            )}
            {detail && !loading && !error && <RcaDetail detail={detail} />}
          </div>
        </div>
      )}
    </div>
  );
}

function RcaDetail({ detail }: { detail: FailureDetail }) {
  const rcaHtml = detail.rca?.summary ? DOMPurify.sanitize(md.render(detail.rca.summary)) : null;
  return (
    <div className="rca-content">
      <h3>Root Cause Analysis</h3>
      {detail.rca ? (
        <>
          <div className="rca-meta">
            <span className={`rca-branch-badge ${detail.rca.branch_taken}`}>
              {detail.rca.branch_taken === "wiki_hit" ? "Wiki hit" : "Novel — reasoned"}
            </span>
            {detail.rca.wiki_doc_path && (
              <span>
                Wiki: <code>{detail.rca.wiki_doc_path}</code>
                {detail.rca.wiki_doc_created ? " (new)" : ""}
              </span>
            )}
            {detail.rca.model_used && (
              <span>
                Model: <code>{detail.rca.model_used}</code>
              </span>
            )}
            {detail.rca.latency_ms != null && <span>{detail.rca.latency_ms} ms</span>}
          </div>
          {rcaHtml && (
            <article className="rca-markdown" dangerouslySetInnerHTML={{ __html: rcaHtml }} />
          )}
        </>
      ) : (
        <p className="rca-placeholder">No RCA for this failure yet.</p>
      )}
      {detail.stacktraces.length > 0 && (
        <>
          <h4>Stack trace</h4>
          {detail.stacktraces.map((s) => (
            <StacktraceView key={s.id} stacktrace={s} />
          ))}
        </>
      )}
      {detail.diffs && detail.diffs.length > 0 && (
        <>
          <h4>Latest change (diff)</h4>
          {detail.diffs.map((d) => (
            <DiffView key={d.id} diff={d} />
          ))}
        </>
      )}
    </div>
  );
}

function StacktraceView({ stacktrace }: { stacktrace: Stacktrace }) {
  const [expanded, setExpanded] = useState(false);
  const hasFull = !!stacktrace.full_text && stacktrace.full_text !== stacktrace.excerpt;
  const shown = expanded && stacktrace.full_text ? stacktrace.full_text : stacktrace.excerpt;

  const copy = () => {
    void navigator.clipboard?.writeText(stacktrace.full_text ?? shown);
  };

  return (
    <div className="stacktrace-block">
      <div className="stacktrace-toolbar">
        <span className="stacktrace-meta">{stacktrace.line_count} lines</span>
        <span className="stacktrace-actions">
          {hasFull && (
            <button type="button" className="btn-link" onClick={() => setExpanded((v) => !v)}>
              {expanded ? "Show tail only" : "Show full log"}
            </button>
          )}
          <button type="button" className="btn-link" onClick={copy}>
            Copy
          </button>
        </span>
      </div>
      <pre className="stacktrace">{shown}</pre>
    </div>
  );
}

function DiffView({ diff }: { diff: CommitDiff }) {
  return (
    <div className="diff-block">
      <div className="diff-meta">
        {diff.ref && <code>{diff.ref}</code>}
        <span>{diff.files_changed} files</span>
        <span className="diff-add">+{diff.additions}</span>
        <span className="diff-del">-{diff.deletions}</span>
        {diff.truncated && <span className="badge">truncated</span>}
      </div>
      {diff.patch ? (
        <pre className="diff-patch">{diff.patch}</pre>
      ) : (
        <p className="rca-placeholder">No patch captured.</p>
      )}
    </div>
  );
}
