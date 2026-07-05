"""Latest-diff fetch tests (GitHub API mocked)."""

from __future__ import annotations

from typing import Any

from tracebow.services import repohost


def _patch_token(monkeypatch) -> None:
    # Skip the DB credential lookup; pretend a global token is configured.
    monkeypatch.setattr(repohost, "_github_token", lambda identifier: "ghp_test")


def test_non_github_provider_returns_none(monkeypatch) -> None:
    _patch_token(monkeypatch)
    assert repohost.fetch_latest_diff("jenkins", "nightly", {}) is None


def test_fetch_commit_diff(monkeypatch) -> None:
    _patch_token(monkeypatch)

    def _fake_get_json(url: str, **kwargs: Any) -> dict[str, Any]:
        assert "commits/deadbeef" in url
        return {
            "status": "ok",
            "data": {
                "files": [
                    {
                        "filename": "app.py",
                        "status": "modified",
                        "additions": 3,
                        "deletions": 1,
                        "patch": "@@ -1 +1 @@\n-old\n+new",
                    }
                ]
            },
        }

    monkeypatch.setattr(repohost, "get_json", _fake_get_json)

    diff = repohost.fetch_latest_diff("github", "acme/api", {"commit_sha": "deadbeef"})
    assert diff is not None
    assert diff["files_changed"] == 1
    assert diff["additions"] == 3
    assert diff["deletions"] == 1
    assert "app.py" in diff["patch"]
    assert diff["truncated"] is False
    assert diff["ref"] == "deadbeef"


def test_fetch_pr_diff_prefers_pr(monkeypatch) -> None:
    _patch_token(monkeypatch)

    def _fake_get_json(url: str, **kwargs: Any) -> dict[str, Any]:
        assert "pulls/42/files" in url
        return {
            "status": "ok",
            "data": [
                {
                    "filename": "a.py",
                    "status": "modified",
                    "additions": 1,
                    "deletions": 0,
                    "patch": "@@ +1 @@\n+x",
                }
            ],
        }

    monkeypatch.setattr(repohost, "get_json", _fake_get_json)

    diff = repohost.fetch_latest_diff(
        "github",
        "acme/api",
        {"pull_request_number": 42, "commit_sha": "deadbeef"},
    )
    assert diff is not None
    assert diff["ref"] == "PR #42"


def test_no_token_returns_none(monkeypatch) -> None:
    monkeypatch.setattr(repohost, "_github_token", lambda identifier: None)
    assert repohost.fetch_latest_diff("github", "acme/api", {"commit_sha": "x"}) is None


def test_truncates_large_patch(monkeypatch) -> None:
    _patch_token(monkeypatch)
    big = "x" * (repohost.MAX_PATCH_CHARS + 100)

    def _fake_get_json(url: str, **kwargs: Any) -> dict[str, Any]:
        return {
            "status": "ok",
            "data": {
                "files": [
                    {
                        "filename": "big.py",
                        "status": "modified",
                        "additions": 1,
                        "deletions": 0,
                        "patch": big,
                    }
                ]
            },
        }

    monkeypatch.setattr(repohost, "get_json", _fake_get_json)
    diff = repohost.fetch_latest_diff("github", "acme/api", {"commit_sha": "abc"})
    assert diff is not None
    assert diff["truncated"] is True
    assert diff["patch"].endswith("... (truncated)")
