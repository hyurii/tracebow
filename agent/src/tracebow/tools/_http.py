"""Shared sync HTTP helper for native tools.

Celery workers are sync, LangGraph's tool invocation is sync, and
``httpx.Client`` is the simplest path. A tiny wrapper keeps timeouts
and auth consistent.
"""

from __future__ import annotations

from typing import Any

import httpx

DEFAULT_TIMEOUT = 15.0


def get_json(
    url: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    auth: tuple[str, str] | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> dict[str, Any]:
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
        ctype = resp.headers.get("content-type", "")
        if "application/json" in ctype:
            return {"status": "ok", "data": resp.json()}
        return {"status": "ok", "data": resp.text}
    except httpx.HTTPStatusError as exc:
        return {
            "status": "error",
            "http_status": exc.response.status_code,
            "error": exc.response.text[:500],
        }
    except httpx.HTTPError as exc:
        return {"status": "error", "error": f"{type(exc).__name__}: {exc}"}


def post_json(
    url: str,
    *,
    json: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    auth: tuple[str, str] | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> dict[str, Any]:
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
        if "application/json" in resp.headers.get("content-type", ""):
            return {"status": "ok", "data": resp.json()}
        return {"status": "ok", "data": resp.text}
    except httpx.HTTPStatusError as exc:
        return {
            "status": "error",
            "http_status": exc.response.status_code,
            "error": exc.response.text[:500],
        }
    except httpx.HTTPError as exc:
        return {"status": "error", "error": f"{type(exc).__name__}: {exc}"}
