"""Egress classification + recording tests (no DB writes)."""

from __future__ import annotations

from tracebow.services import egress


def test_classify_internal_hosts() -> None:
    assert egress.classify_host("http://ollama:11434/api/tags") == egress.INTERNAL
    assert egress.classify_host("http://localhost:8080") == egress.INTERNAL
    assert egress.classify_host("postgres") == egress.INTERNAL


def test_classify_external_hosts() -> None:
    assert egress.classify_host("https://api.github.com/repos") == egress.EXTERNAL
    assert egress.classify_host("git@github.com:acme/wiki.git") == egress.EXTERNAL
    assert egress.classify_host("https://acme.atlassian.net") == egress.EXTERNAL


def test_record_http_scans_and_forwards(monkeypatch) -> None:
    captured: dict = {}

    def _fake_record(**kwargs) -> None:
        captured.update(kwargs)

    monkeypatch.setattr(egress, "record_egress", _fake_record)

    flags = egress.record_http(
        "https://api.github.com/repos/acme/api",
        method="GET",
        purpose="fetch_latest_diff",
        request_payload="token ghp_abcdefghijklmnopqrstuvwxyz012345",
        response_text="{}",
        status="ok",
    )

    assert "github_token" in flags
    assert captured["host"] == "https://api.github.com/repos/acme/api"
    assert captured["purpose"] == "fetch_latest_diff"
    assert captured["method"] == "GET"
    assert captured["sensitive_flags"] == flags


def test_record_http_clean_payload_has_no_flags(monkeypatch) -> None:
    monkeypatch.setattr(egress, "record_egress", lambda **kwargs: None)
    flags = egress.record_http(
        "https://api.github.com/repos/acme/api",
        method="GET",
        purpose="list_github_runs",
        request_payload="https://api.github.com/repos/acme/api",
        response_text="{}",
        status="ok",
    )
    assert flags == []
