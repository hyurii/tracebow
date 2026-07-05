"""Unit tests for the outbound sensitive-data scanner."""

from __future__ import annotations

from tracebow.services.sensitive import scan_sensitive


def test_empty_and_clean_text_has_no_flags() -> None:
    assert scan_sensitive(None) == []
    assert scan_sensitive("") == []
    assert scan_sensitive("just a normal repo name acme/api and a job") == []


def test_detects_private_key_block() -> None:
    # Build the header at runtime so the literal PEM marker isn't present in
    # source (keeps detect-private-key / secret scanners from flagging tests).
    header = "-----BEGIN OPENSSH " + "PRIVATE KEY-----"
    text = f"{header}\nabc\n-----END..."
    assert "private_key" in scan_sensitive(text)


def test_detects_github_token() -> None:
    flags = scan_sensitive("token is ghp_abcdefghijklmnopqrstuvwxyz0123456789")
    assert "github_token" in flags


def test_detects_aws_key_and_email() -> None:
    flags = scan_sensitive("AKIAIOSFODNN7EXAMPLE sent to alice@example.com")
    assert "aws_access_key" in flags
    assert "email" in flags


def test_returns_sorted_unique_labels() -> None:
    flags = scan_sensitive("alice@example.com and bob@example.com")
    assert flags == ["email"]
