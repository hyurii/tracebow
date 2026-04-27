import { useEffect, useMemo, useState } from "react";
import DOMPurify from "dompurify";
import MarkdownIt from "markdown-it";
import { api } from "../api";
import type { WikiDoc, WikiDocContent, WikiSearchHit } from "../types";

const md = new MarkdownIt({ html: false, linkify: true, breaks: false });

type TreeNode = {
  name: string;
  path: string;
  kind: "file" | "folder";
  children: TreeNode[];
  doc?: WikiDoc;
};

function buildTree(docs: WikiDoc[]): TreeNode {
  const root: TreeNode = { name: "", path: "", kind: "folder", children: [] };
  const sorted = [...docs].sort((a, b) => a.path.localeCompare(b.path));

  for (const doc of sorted) {
    const parts = doc.path.split("/");
    let cursor = root;
    for (let i = 0; i < parts.length; i++) {
      const isLeaf = i === parts.length - 1;
      const name = parts[i];
      const fullPath = parts.slice(0, i + 1).join("/");
      let child = cursor.children.find((c) => c.name === name);
      if (!child) {
        child = {
          name,
          path: fullPath,
          kind: isLeaf ? "file" : "folder",
          children: [],
          doc: isLeaf ? doc : undefined,
        };
        cursor.children.push(child);
      }
      cursor = child;
    }
  }
  return root;
}

function TreeView({
  node,
  onSelect,
  activePath,
  depth = 0,
}: {
  node: TreeNode;
  onSelect: (path: string) => void;
  activePath: string | null;
  depth?: number;
}) {
  const [open, setOpen] = useState(depth < 1);
  if (node.kind === "file") {
    return (
      <li
        className={`wiki-tree-file ${activePath === node.path ? "active" : ""}`}
        style={{ paddingLeft: `${depth * 0.75}rem` }}
        onClick={() => onSelect(node.path)}
      >
        {node.doc?.title ?? node.name.replace(/\.md$/, "")}
      </li>
    );
  }
  return (
    <li className="wiki-tree-folder">
      <div
        className="wiki-tree-folder-name"
        style={{ paddingLeft: `${depth * 0.75}rem` }}
        onClick={() => setOpen((o) => !o)}
      >
        {open ? "▾" : "▸"} {node.name || "/"}
      </div>
      {open && (
        <ul>
          {node.children.map((child) => (
            <TreeView
              key={child.path}
              node={child}
              onSelect={onSelect}
              activePath={activePath}
              depth={depth + 1}
            />
          ))}
        </ul>
      )}
    </li>
  );
}

export function WikiBrowser() {
  const [docs, setDocs] = useState<WikiDoc[]>([]);
  const [listError, setListError] = useState<string | null>(null);
  const [activePath, setActivePath] = useState<string | null>(null);
  const [content, setContent] = useState<WikiDocContent | null>(null);
  const [contentError, setContentError] = useState<string | null>(null);
  const [loadingContent, setLoadingContent] = useState(false);

  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<WikiSearchHit[]>([]);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .listWiki()
      .then((data) => {
        if (cancelled) return;
        setDocs(data.docs);
        setActivePath((current) => {
          if (current) return current;
          return data.docs.length > 0 ? data.docs[0].path : null;
        });
      })
      .catch((err) => setListError(String(err.message ?? err)));
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!activePath) return;
    let cancelled = false;
    setLoadingContent(true);
    setContentError(null);
    api
      .readWiki(activePath)
      .then((doc) => {
        if (!cancelled) setContent(doc);
      })
      .catch((err) => {
        if (!cancelled) setContentError(String(err.message ?? err));
      })
      .finally(() => {
        if (!cancelled) setLoadingContent(false);
      });
    return () => {
      cancelled = true;
    };
  }, [activePath]);

  const tree = useMemo(() => buildTree(docs), [docs]);

  const renderedHtml = useMemo(() => {
    if (!content) return "";
    const html = md.render(content.content);
    return DOMPurify.sanitize(html);
  }, [content]);

  const runSearch = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!query.trim()) {
      setHits([]);
      return;
    }
    setSearching(true);
    setSearchError(null);
    try {
      const data = await api.searchWiki(query.trim());
      setHits(data.hits);
    } catch (err) {
      setSearchError(String((err as Error).message ?? err));
    } finally {
      setSearching(false);
    }
  };

  return (
    <div className="wiki-browser">
      <aside className="wiki-sidebar">
        <form onSubmit={runSearch} className="wiki-search">
          <input
            type="search"
            placeholder="Search wiki…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <button type="submit" disabled={searching}>
            {searching ? "…" : "Search"}
          </button>
        </form>
        {searchError && <p className="wiki-error">{searchError}</p>}
        {hits.length > 0 && (
          <div className="wiki-search-results">
            <h4>Search results</h4>
            <ul>
              {hits.map((hit) => (
                <li
                  key={hit.path}
                  className={activePath === hit.path ? "active" : ""}
                  onClick={() => setActivePath(hit.path)}
                >
                  <div className="hit-title">{hit.title}</div>
                  <div className="hit-path">{hit.path}</div>
                  <div className="hit-snippet">{hit.snippet}</div>
                </li>
              ))}
            </ul>
            <button className="btn-link" onClick={() => setHits([])}>
              Clear search
            </button>
          </div>
        )}
        <h4>All docs</h4>
        {listError && <p className="wiki-error">{listError}</p>}
        {!listError && docs.length === 0 && (
          <p className="empty-state">
            Wiki is empty. The agent will create pages here as it resolves
            failures.
          </p>
        )}
        <ul className="wiki-tree">
          {tree.children.map((child) => (
            <TreeView
              key={child.path}
              node={child}
              onSelect={setActivePath}
              activePath={activePath}
            />
          ))}
        </ul>
      </aside>
      <section className="wiki-content">
        {loadingContent && <p>Loading…</p>}
        {contentError && <p className="wiki-error">{contentError}</p>}
        {!loadingContent && content && (
          <>
            <header className="wiki-content-header">
              <h2>{content.title}</h2>
              <p className="wiki-content-path">{content.path}</p>
              {content.updated_at && (
                <p className="wiki-content-meta">
                  Updated {new Date(content.updated_at).toLocaleString()}
                </p>
              )}
            </header>
            <article
              className="wiki-markdown"
              dangerouslySetInnerHTML={{ __html: renderedHtml }}
            />
          </>
        )}
        {!loadingContent && !content && !contentError && (
          <p className="empty-state">Select a document to preview it.</p>
        )}
      </section>
    </div>
  );
}
