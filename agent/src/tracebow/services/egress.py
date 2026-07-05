"""Egress monitoring — record every outbound network attempt.

Called from the two choke points where Tracebow can talk to the outside world:
the shared HTTP helper (:mod:`tracebow.tools._http`) and the wiki push
(:meth:`tracebow.services.wiki.WikiService.push`). Each attempt becomes an
:class:`~tracebow.db.EgressEvent` powering the portal's Security page.

A host is *internal* when it is part of the local zero-egress stack (ollama,
postgres, redis, localhost); everything else is *external*.
"""

from __future__ import annotations

import asyncio
import logging
from urllib.parse import urlsplit

from tracebow.config import get_settings
from tracebow.db import EgressEvent, get_session_factory
from tracebow.services.sensitive import scan_sensitive

logger = logging.getLogger(__name__)

INTERNAL = "internal"
EXTERNAL = "external"

# Hostnames that are part of the local, in-network stack.
_INTERNAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "ollama", "postgres", "redis", "db"})


def _host_of(url_or_host: str) -> str:
    if "://" in url_or_host:
        host = urlsplit(url_or_host).hostname or url_or_host
    else:
        # bare host[:port] or scp-like ``git@host:path``
        host = url_or_host.split(":", 1)[0]
        if "@" in host:
            host = host.rsplit("@", 1)[1]
    return host.lower()


def classify_host(url_or_host: str) -> str:
    """Return ``internal`` or ``external`` for a URL or bare host."""
    host = _host_of(url_or_host)
    if host in _INTERNAL_HOSTS:
        return INTERNAL
    # The configured Ollama endpoint is always internal, whatever its host.
    try:
        ollama_host = _host_of(get_settings().ollama_base_url)
    except Exception:
        ollama_host = ""
    if host and host == ollama_host:
        return INTERNAL
    return EXTERNAL


def _run(coro: object) -> None:
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(coro)  # type: ignore[arg-type]
    finally:
        loop.close()


def record_egress(
    *,
    host: str,
    purpose: str | None,
    method: str | None,
    request_bytes: int = 0,
    response_bytes: int = 0,
    status: str | None = None,
    sensitive_flags: list[str] | None = None,
    blocked: bool = False,
    kind: str | None = None,
) -> None:
    """Persist one egress event. Best-effort — never raises into callers."""
    destination_kind = kind or classify_host(host)
    clean_host = _host_of(host)

    async def _inner() -> None:
        sm = get_session_factory()
        async with sm() as session:
            session.add(
                EgressEvent(
                    destination_host=clean_host,
                    destination_kind=destination_kind,
                    purpose=purpose,
                    method=method,
                    request_bytes=request_bytes,
                    response_bytes=response_bytes,
                    status=status,
                    sensitive_flags=sensitive_flags or None,
                    blocked=blocked,
                )
            )
            await session.commit()

    try:
        _run(_inner())
    except Exception:
        # Observability must never break the actual request path.
        logger.debug("Failed to record egress event for %s", clean_host, exc_info=True)


def record_http(
    url: str,
    *,
    method: str,
    purpose: str | None,
    request_payload: str | None = None,
    response_text: str | None = None,
    status: str | None = None,
) -> list[str]:
    """Scan an outbound HTTP call for secrets and record it. Returns flags."""
    flags = scan_sensitive(request_payload)
    record_egress(
        host=url,
        purpose=purpose,
        method=method,
        request_bytes=len(request_payload or ""),
        response_bytes=len(response_text or ""),
        status=status,
        sensitive_flags=flags,
    )
    return flags
