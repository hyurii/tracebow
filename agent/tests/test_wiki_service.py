"""
Unit tests for ``WikiService``.

These are pure filesystem + git tests: no network, no LLM.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tracebow.services.wiki import WikiError, WikiService


def test_init_creates_repo_and_seeds_readme(tmp_path: Path) -> None:
    svc = WikiService(root=tmp_path / "wiki")
    svc.init_if_needed()

    assert (tmp_path / "wiki" / ".git").is_dir()
    assert (tmp_path / "wiki" / "README.md").is_file()
    assert (tmp_path / "wiki" / "runbooks").is_dir()
    assert (tmp_path / "wiki" / "policies").is_dir()


def test_init_is_idempotent(tmp_path: Path) -> None:
    svc = WikiService(root=tmp_path / "wiki")
    svc.init_if_needed()
    svc.init_if_needed()
    assert (tmp_path / "wiki" / ".git").is_dir()


def test_write_creates_file_and_commits(wiki_service: WikiService) -> None:
    result = wiki_service.write(
        "runbooks/db-timeout.md",
        "# DB timeout\n\nRestart pgbouncer.\n",
        message="add db-timeout runbook",
    )
    assert result.created is True
    assert result.commit_sha is not None
    assert (wiki_service.root / "runbooks" / "db-timeout.md").read_text().startswith("# DB timeout")


def test_write_is_noop_on_identical_content(wiki_service: WikiService) -> None:
    wiki_service.write("runbooks/x.md", "# X\n")
    second = wiki_service.write("runbooks/x.md", "# X\n")
    assert second.created is False
    assert second.commit_sha is None


def test_write_rejects_non_markdown(wiki_service: WikiService) -> None:
    with pytest.raises(WikiError):
        wiki_service.write("runbooks/oops.txt", "nope")


def test_write_rejects_path_traversal(wiki_service: WikiService) -> None:
    with pytest.raises(WikiError):
        wiki_service.write("../evil.md", "nope")


def test_read_returns_title_and_content(wiki_service: WikiService) -> None:
    wiki_service.write(
        "runbooks/hello.md",
        "# Hello\n\nBody text here.\n",
    )
    doc = wiki_service.read("runbooks/hello.md")
    assert doc.path == "runbooks/hello.md"
    assert doc.title == "Hello"
    assert "Body text here." in doc.content


def test_search_ranks_filename_higher_than_body(wiki_service: WikiService) -> None:
    wiki_service.write("runbooks/db-timeout.md", "# DB timeout\n\nOpen a new connection.\n")
    wiki_service.write(
        "runbooks/general-tips.md",
        "# General\n\nUnrelated database timeout mention.\n",
    )

    hits = wiki_service.search("db timeout")
    assert hits, "expected at least one search hit"
    assert hits[0].path == "runbooks/db-timeout.md"


def test_list_docs_returns_sorted_summaries(wiki_service: WikiService) -> None:
    wiki_service.write("runbooks/alpha.md", "# Alpha\n")
    wiki_service.write("runbooks/beta.md", "# Beta\n")

    docs = wiki_service.list_docs()
    paths = [d.path for d in docs]
    assert "README.md" in paths
    assert "runbooks/alpha.md" in paths
    assert "runbooks/beta.md" in paths
    assert paths == sorted(paths)
