"""Shared sync HTTP helper for native tools.

Celery workers are sync, LangGraph's tool invocation is sync, and
``httpx.Client`` is the simplest path. A tiny wrapper keeps timeouts
and auth consistent — and records every outbound call as an egress event
so the Security page can show exactly what leaves the network.
"""

from __future__ import annotations

import json as _json
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 15.0


def _record(
    url: str,
    method: str,
    purpose: str | None,
    request_payload: str,
    response_text: str,
    status: str,
) -> None:
    # Import lazily to avoid import cycles and to keep monitoring best-effort.
    try:
        from tracebow.services.egress import record_http

        record_http(
            url,
            method=method,
            purpose=purpose,
            request_payload=request_payload,
            response_text=response_text,
            status=status,
        )
    except Exception:
        # Monitoring must never break the request path.
        logger.debug("Failed to record egress for %s", url, exc_info=True)


def get_json(
    url: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    auth: tuple[str, str] | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    purpose: str | None = None,
) -> dict[str, Any]:
    # Scan the URL + query values (never the auth header — that is the
    # expected credential, not a leak).
    req_payload = url if not params else f"{url} {params}"
    resp_text = ""
    status = "error"
    try:
        resp = httpx.get(
            url,
            params=params,
            headers=headers,
            auth=auth,
            timeout=timeout,
            follow_redirects=True,
        )
        resp.raise_for_status()
        resp_text = resp.text
        status = "ok"
        ctype = resp.headers.get("content-type", "")
        if "application/json" in ctype:
            return {"status": "ok", "data": resp.json()}
        return {"status": "ok", "data": resp.text}
    except httpx.HTTPStatusError as exc:
        resp_text = exc.response.text
        status = f"http_{exc.response.status_code}"
        return {
            "status": "error",
            "http_status": exc.response.status_code,
            "error": exc.response.text[:500],
        }
    except httpx.HTTPError as exc:
        status = f"error:{type(exc).__name__}"
        return {"status": "error", "error": f"{type(exc).__name__}: {exc}"}
    finally:
        _record(url, "GET", purpose, req_payload, resp_text, status)


def post_json(
    url: str,
    *,
    json: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    auth: tuple[str, str] | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    purpose: str | None = None,
) -> dict[str, Any]:
    req_payload = url if json is None else f"{url} {_json.dumps(json, default=str)}"
    resp_text = ""
    status = "error"
    try:
        resp = httpx.post(
            url,
            json=json,
            headers=headers,
            auth=auth,
            timeout=timeout,
            follow_redirects=True,
        )
        resp.raise_for_status()
        resp_text = resp.text
        status = "ok"
        if "application/json" in resp.headers.get("content-type", ""):
            return {"status": "ok", "data": resp.json()}
        return {"status": "ok", "data": resp.text}
    except httpx.HTTPStatusError as exc:
        resp_text = exc.response.text
        status = f"http_{exc.response.status_code}"
        return {
            "status": "error",
            "http_status": exc.response.status_code,
            "error": exc.response.text[:500],
        }
    except httpx.HTTPError as exc:
        status = f"error:{type(exc).__name__}"
        return {"status": "error", "error": f"{type(exc).__name__}: {exc}"}
    finally:
        _record(url, "POST", purpose, req_payload, resp_text, status)
