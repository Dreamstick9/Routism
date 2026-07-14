"""Honest worker health classification for models-endpoint probes.

Both ``GET /v1/management/health/{id}`` and ``GET /v1/health`` must use the
same rule so the Providers UI cannot disagree with the management probe:

  reachable == True  only for HTTP 2xx
  401 / 403 / 404 / 5xx / other non-2xx → reachable False + clear error

Probes are lightweight GET to a models metadata URL — never a chat completion.
"""
from __future__ import annotations

from typing import Any


def is_healthy_status(status_code: int | None) -> bool:
    """True only for successful 2xx responses."""
    if status_code is None:
        return False
    try:
        code = int(status_code)
    except (TypeError, ValueError):
        return False
    return 200 <= code < 300


def health_error_for_status(status_code: int | None) -> str | None:
    """Human-readable failure class for a non-healthy models probe, or None if OK."""
    if is_healthy_status(status_code):
        return None
    if status_code is None:
        return "no HTTP response"
    try:
        code = int(status_code)
    except (TypeError, ValueError):
        return f"invalid status {status_code!r}"

    if code == 401:
        return "unauthorized (401) — check API key"
    if code == 403:
        return "forbidden (403) — check API key or permissions"
    if code == 404:
        return "not found (404) — models endpoint missing or wrong base URL"
    if code == 429:
        return "rate limited (429)"
    if 500 <= code <= 599:
        return f"server error ({code})"
    if 400 <= code < 500:
        return f"client error ({code})"
    return f"HTTP {code}"


def models_probe_url(base_url: str) -> str:
    """Derive the lightweight models metadata URL from a worker base_url."""
    base = (base_url or "").rstrip("/")
    if not base:
        return "/v1/models"
    if base.endswith("/v1"):
        return base + "/models"
    return base + "/v1/models"


def classify_models_probe(
    *,
    worker_id: str,
    status_code: int | None,
    api_key_configured: bool,
    url: str,
    transport_error: str | None = None,
) -> dict[str, Any]:
    """Build the standard health result dict used by management + aggregate health."""
    if transport_error:
        return {
            "id": worker_id,
            "reachable": False,
            "status_code": status_code,
            "api_key_configured": bool(api_key_configured),
            "url": url,
            "error": transport_error,
        }
    ok = is_healthy_status(status_code)
    return {
        "id": worker_id,
        "reachable": ok,
        "status_code": status_code,
        "api_key_configured": bool(api_key_configured),
        "url": url,
        "error": None if ok else health_error_for_status(status_code),
    }


def fetch_models_error_for_status(status_code: int) -> str:
    """Error string for ``POST /v1/management/fetch-models`` non-2xx responses."""
    err = health_error_for_status(status_code)
    if err:
        return err
    return f"server returned {status_code}"
