"""
WikiService — Git-backed Markdown knowledge base.

Contract:
* ``WIKI_PATH`` is a persistent directory bind-mounted into the container.
* On first boot, ``init_if_needed()`` runs ``git init`` and creates
  ``runbooks/`` + ``policies/`` + ``README.md``.
* ``search()`` does a filename + full-text scan (no external deps — just
  the filesystem). Returns ranked hits.
* ``read()`` / ``write()`` are straightforward file I/O restricted to
  ``WIKI_PATH``. ``write()`` auto-commits with a deterministic author.
* ``push()`` optionally sends the working branch to a remote over SSH
  using a deploy key materialized from the DB. Called only by the
  Celery beat job or by the "Backup now" button.

The service is deliberately synchronous — the filesystem + git shelling
is fast enough that we don't need async overhead, and LangGraph tools
run inside a worker where sync is fine.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import stat
import subprocess  # nosec B404 - `git` invocation is tightly scoped below
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from git import Actor, GitCommandError, Repo

from tracebow.config import get_settings

logger = logging.getLogger(__name__)

_ALLOWED_EXT = {".md", ".markdown"}

# A very small, handwritten stopword list. We do not ship an NLP library —
# the wiki is not a general-purpose search engine. Its only job is to rank
# runbooks by shared *signal* tokens (job/repo/error keywords).
_STOPWORDS = frozenset(
    {
        "the",
        "and",
        "for",
        "with",
        "from",
        "into",
        "this",
        "that",
        "have",
        "will",
        "when",
        "then",
        "your",
        "ours",
        "them",
        "they",
        "there",
        "here",
        "where",
        "which",
        "while",
        "about",
        "been",
        "were",
        "what",
        "over",
        "http",
        "https",
        "null",
        "none",
    }
)


@dataclass(frozen=True)
class WikiSearchHit:
    path: str
    title: str
    excerpt: str
    score: float


@dataclass(frozen=True)
class WikiDocument:
    path: str
    title: str
    content: str
    size: int
    updated_at: str | None = None


@dataclass(frozen=True)
class WikiDocSummary:
    path: str
    title: str
    size: int
    updated_at: str | None


@dataclass(frozen=True)
class WikiWriteResult:
    path: str
    created: bool
    commit_sha: str | None


class WikiError(Exception):
    """Raised for all wiki-related failures."""


# Conservative whitelists for things we feed into ``git push`` argv.
# Even though the values come from a Postgres row that an operator filled in
# via the portal, we still validate to keep the bandit B603 suppression
# honest: an attacker who can write to that row should not be able to inject
# git flags or shell metacharacters via this code path.
_REMOTE_URL_RE = re.compile(
    r"^(?:[\w.+-]+@[\w.-]+:[\w./@:~+-]+|"
    r"https?://[\w.-]+(?::\d+)?/[\w./@:~+-]+|"
    r"ssh://[\w.+-]+@[\w.-]+(?::\d+)?/[\w./@:~+-]+|"
    r"git://[\w.-]+(?::\d+)?/[\w./@:~+-]+)$"
)
_BRANCH_RE = re.compile(r"^[A-Za-z0-9_./-]{1,200}$")


def _validate_remote_url(url: str) -> None:
    if not url or url.startswith("-") or not _REMOTE_URL_RE.match(url):
        raise WikiError(f"refusing to push: invalid remote URL: {url!r}")


def _validate_branch(branch: str) -> None:
    if not branch or branch.startswith("-") or not _BRANCH_RE.match(branch):
        raise WikiError(f"refusing to push: invalid branch name: {branch!r}")


class WikiService:
    """Thin wrapper over a local Git repo used as the knowledge base."""

    def __init__(
        self,
        root: str | Path | None = None,
        default_branch: str | None = None,
    ) -> None:
        settings = get_settings()
        self.root = Path(root or settings.wiki_path).resolve()
        self.default_branch = default_branch or settings.wiki_default_branch
        self.author_name = settings.wiki_author_name
        self.author_email = settings.wiki_author_email

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def init_if_needed(self) -> None:
        """Idempotent ``git init`` + seed. Safe to call on every startup."""
        self.root.mkdir(parents=True, exist_ok=True)
        git_dir = self.root / ".git"
        if not git_dir.exists():
            logger.info("Initializing wiki repo at %s", self.root)
            repo = Repo.init(self.root, initial_branch=self.default_branch)
            self._seed(repo)
        else:
            # Ensure the configured branch exists
            repo = Repo(self.root)
            if repo.head.is_detached or repo.active_branch.name != self.default_branch:
                try:
                    repo.git.checkout(self.default_branch)
                except GitCommandError:
                    logger.warning(
                        "Could not check out %s — leaving HEAD as-is",
                        self.default_branch,
                    )

    def _seed(self, repo: Repo) -> None:
        (self.root / "runbooks").mkdir(exist_ok=True)
        (self.root / "policies").mkdir(exist_ok=True)
        readme = self.root / "README.md"
        if not readme.exists():
            readme.write_text(
                "# Tracebow Wiki\n\n"
                "This repository is Tracebow's knowledge base. The AI agent reads\n"
                "and writes Markdown runbooks under `runbooks/` when it resolves a\n"
                "pipeline failure. Policies and other long-lived notes live under\n"
                "`policies/`.\n\n"
                "Engineers can clone this repo and edit it with any Markdown editor;\n"
                "changes are picked up on the next search.\n",
                encoding="utf-8",
            )
        placeholder = self.root / "runbooks" / ".gitkeep"
        placeholder.write_text("", encoding="utf-8")
        (self.root / "policies" / ".gitkeep").write_text("", encoding="utf-8")
        repo.index.add(["README.md", "runbooks/.gitkeep", "policies/.gitkeep"])
        repo.index.commit(
            "Seed Tracebow wiki",
            author=Actor(self.author_name, self.author_email),
            committer=Actor(self.author_name, self.author_email),
        )

    # ------------------------------------------------------------------
    # Read / search
    # ------------------------------------------------------------------
    def list_docs(self) -> list[WikiDocSummary]:
        """List every markdown file as a summary suitable for the portal tree."""
        out: list[WikiDocSummary] = []
        for path in self._iter_markdown():
            try:
                stat_result = path.stat()
            except OSError:
                continue
            try:
                content = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                content = ""
            updated = (
                datetime.fromtimestamp(stat_result.st_mtime, tz=UTC).isoformat()
                if stat_result.st_mtime
                else None
            )
            out.append(
                WikiDocSummary(
                    path=self._rel(path),
                    title=self._extract_title(content) or path.stem,
                    size=stat_result.st_size,
                    updated_at=updated,
                )
            )
        out.sort(key=lambda d: d.path)
        return out

    def read(self, relpath: str) -> WikiDocument:
        full = self._safe_path(relpath)
        if not full.is_file():
            raise WikiError(f"Not found: {relpath}")
        content = full.read_text(encoding="utf-8", errors="replace")
        title = self._extract_title(content) or full.stem
        stat_result = full.stat()
        return WikiDocument(
            path=self._rel(full),
            title=title,
            content=content,
            size=stat_result.st_size,
            updated_at=datetime.fromtimestamp(stat_result.st_mtime, tz=UTC).isoformat(),
        )

    def search(self, query: str, limit: int = 10) -> list[WikiSearchHit]:
        """Rank docs by a cheap TF-style score over filename + body.

        No external index is used on purpose — for the expected wiki
        size (dozens to low thousands of docs) this is fast enough and
        removes an entire class of "stale index" bugs.
        """
        raw = re.findall(r"[\w./:\-]+", query)
        terms = [t.lower() for t in raw if len(t) >= 4 and t.lower() not in _STOPWORDS]
        if not terms:
            return []

        hits: list[WikiSearchHit] = []
        for path in self._iter_markdown():
            rel = self._rel(path)
            try:
                body = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            lower_body = body.lower()
            lower_name = rel.lower()
            score = 0.0
            for term in terms:
                score += 3.0 * lower_name.count(term)
                score += lower_body.count(term)
            if score <= 0:
                continue
            title = self._extract_title(body) or path.stem
            excerpt = self._excerpt_for(body, terms)
            hits.append(WikiSearchHit(path=rel, title=title, excerpt=excerpt, score=score))

        hits.sort(key=lambda h: h.score, reverse=True)
        return hits[:limit]

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------
    def write(
        self,
        relpath: str,
        content: str,
        message: str | None = None,
    ) -> WikiWriteResult:
        full = self._safe_path(relpath, must_be_markdown=True)
        full.parent.mkdir(parents=True, exist_ok=True)
        existed = full.exists()
        full.write_text(content, encoding="utf-8")

        repo = Repo(self.root)
        rel = self._rel(full)
        repo.index.add([rel])

        if not repo.is_dirty(index=True, working_tree=False, untracked_files=True):
            # Nothing changed (content identical) — don't create an empty commit.
            return WikiWriteResult(path=rel, created=False, commit_sha=None)

        commit_message = message or (f"{'Create' if not existed else 'Update'} {rel} via agent")
        commit = repo.index.commit(
            commit_message,
            author=Actor(self.author_name, self.author_email),
            committer=Actor(self.author_name, self.author_email),
        )
        logger.info("Wiki commit %s: %s", commit.hexsha[:8], commit_message)
        return WikiWriteResult(path=rel, created=not existed, commit_sha=commit.hexsha)

    # ------------------------------------------------------------------
    # Push (optional, driven by WikiSettings)
    # ------------------------------------------------------------------
    def push(
        self,
        remote_url: str,
        branch: str,
        deploy_key_pem: str | None = None,
    ) -> str:
        """Push ``branch`` to ``remote_url``. Returns a status string.

        If ``deploy_key_pem`` is provided it is written to a 0600 temp
        file and used as ``GIT_SSH_COMMAND`` only for this invocation.
        We shell out directly (no GitPython ``push``) because GitPython
        offers no clean way to override env vars per-call.
        """
        _validate_remote_url(remote_url)
        _validate_branch(branch)
        tmpdir: str | None = None
        try:
            env = os.environ.copy()
            if deploy_key_pem:
                tmpdir = tempfile.mkdtemp(prefix="tracebow-wiki-key-")
                key_path = Path(tmpdir) / "id"
                key_path.write_text(deploy_key_pem, encoding="utf-8")
                os.chmod(key_path, stat.S_IRUSR | stat.S_IWUSR)
                env["GIT_SSH_COMMAND"] = (
                    f"ssh -i {key_path} -o StrictHostKeyChecking=accept-new "
                    "-o IdentitiesOnly=yes -o BatchMode=yes"
                )

            cmd = [
                "git",
                "-C",
                str(self.root),
                "push",
                remote_url,
                f"{branch}:{branch}",
            ]
            # nosec B603 — argv is a fixed list, ``git`` resolved via PATH;
            # ``remote_url`` and ``branch`` are whitelisted above; shell=False.
            result = subprocess.run(  # nosec B603
                cmd,
                env=env,
                capture_output=True,
                text=True,
                check=False,
                timeout=60,
            )
            self._record_push_egress(remote_url, result.returncode)
            if result.returncode != 0:
                stderr = (result.stderr or "").strip() or "unknown error"
                raise WikiError(f"git push failed: {stderr}")
            return (result.stderr or result.stdout or "ok").strip() or "ok"
        finally:
            if tmpdir is not None:
                shutil.rmtree(tmpdir, ignore_errors=True)

    @staticmethod
    def _record_push_egress(remote_url: str, returncode: int) -> None:
        """Best-effort egress record for the wiki backup push."""
        try:
            from tracebow.services.egress import record_egress

            record_egress(
                host=remote_url,
                purpose="wiki_push",
                method="git-push",
                status="ok" if returncode == 0 else f"exit_{returncode}",
            )
        except Exception:
            logger.debug("Failed to record wiki push egress", exc_info=True)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _iter_markdown(self) -> Iterator[Path]:
        for path in self.root.rglob("*"):
            if path.is_file() and path.suffix.lower() in _ALLOWED_EXT:
                if ".git" in path.parts:
                    continue
                yield path

    def _safe_path(self, relpath: str, *, must_be_markdown: bool = False) -> Path:
        if not relpath or relpath.startswith(("/", "\\")):
            raise WikiError("relpath must be repo-relative")
        candidate = (self.root / relpath).resolve()
        try:
            candidate.relative_to(self.root)
        except ValueError as exc:
            raise WikiError(f"Path escapes wiki root: {relpath}") from exc
        if must_be_markdown and candidate.suffix.lower() not in _ALLOWED_EXT:
            raise WikiError("Only .md / .markdown files are allowed")
        return candidate

    def _rel(self, path: Path) -> str:
        return path.resolve().relative_to(self.root).as_posix()

    @staticmethod
    def _extract_title(content: str) -> str | None:
        for line in content.splitlines():
            line = line.strip()
            if line.startswith("#"):
                return line.lstrip("# ").strip() or None
            if line:
                break
        return None

    @staticmethod
    def _excerpt_for(content: str, terms: list[str], window: int = 160) -> str:
        lower = content.lower()
        pos = -1
        for term in terms:
            pos = lower.find(term)
            if pos >= 0:
                break
        if pos < 0:
            snippet = content[:window]
        else:
            start = max(0, pos - window // 2)
            end = min(len(content), pos + window // 2)
            snippet = content[start:end]
        return re.sub(r"\s+", " ", snippet).strip()
