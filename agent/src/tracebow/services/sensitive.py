"""Best-effort sensitive-data detection for outbound payloads.

Used by the egress monitor to flag when data leaving the host *looks* like it
contains a secret or PII. This is a heuristic signal for the security
dashboard, not a guarantee — it exists so an operator can see, at a glance,
whether anything sensitive is going out and where.
"""

from __future__ import annotations

import re

# (label, compiled pattern). Order is not significant; all are checked.
_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("private_key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----")),
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("github_token", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}\b")),
    ("github_pat", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b")),
    ("slack_token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{5,}\b")),
    ("bearer_token", re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._-]{16,}\b")),
    ("email", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
]


def scan_sensitive(text: str | None) -> list[str]:
    """Return a sorted list of sensitive-data category labels found in ``text``."""
    if not text:
        return []
    found: set[str] = set()
    for label, pattern in _PATTERNS:
        if pattern.search(text):
            found.add(label)
    return sorted(found)
