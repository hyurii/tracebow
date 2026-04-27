"""Symmetric encryption for small secrets (wiki deploy key).

Why not Docker secrets or a KMS: this project targets a single-EC2
zero-egress deployment; adding external KMS breaks the air-gapped
promise. We derive a Fernet key from ``WIKI_SECRET_KEY`` (operator-set
env var) and encrypt the deploy key at rest in Postgres. Readers hold
a matching env var; no decryption is possible on a stolen DB dump alone.
"""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from tracebow.config import get_settings


def _derive_fernet_key(secret: str) -> bytes:
    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


def _fernet() -> Fernet:
    return Fernet(_derive_fernet_key(get_settings().wiki_secret_key))


def encrypt(plaintext: str) -> bytes:
    """Encrypt a string. Returns ciphertext bytes (UTF-8 safe)."""
    return _fernet().encrypt(plaintext.encode("utf-8"))


def decrypt(ciphertext: bytes) -> str:
    """Decrypt previously-stored ciphertext. Raises InvalidToken on tampering or key mismatch."""
    try:
        return _fernet().decrypt(ciphertext).decode("utf-8")
    except InvalidToken as exc:
        raise ValueError("Unable to decrypt secret — WIKI_SECRET_KEY may have changed.") from exc


def fingerprint(plaintext: str) -> str:
    """Short, non-reversible identifier for a secret (for display in UI)."""
    return "sha256:" + hashlib.sha256(plaintext.encode("utf-8")).hexdigest()[:16]
