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


def normalize_openai_base_url(url: str) -> str:
    """Normalize a worker base URL to an OpenAI-compatible API root.

    Accepts (and repairs) common misconfigurations:
      - ``…/v1``                         → unchanged
      - ``…/v1/``                        → strip trailing slash
      - ``…/v1/chat/completions``        → ``…/v1``  (catalog bug / copy-paste)
      - ``…/v1/models``                  → ``…/v1``
      - bare host ``https://api.x.com``  → unchanged (caller may append /v1)

    Never leaves a ``/chat/completions`` path in the base — that breaks health
    probes (GET …/chat/completions/v1/models → 404).
    """
    u = (url or "").strip()
    if not u:
        return ""
    u = u.rstrip("/")
    # Drop full chat path if someone stored the chat URL as base_url
    if "/chat/completions" in u:
        u = u.split("/chat/completions", 1)[0].rstrip("/")
    # Drop /models suffix if a models list URL was stored as base
    if u.endswith("/models"):
        u = u[: -len("/models")].rstrip("/")
    return u


def models_probe_url(base_url: str) -> str:
    """Derive the lightweight models metadata URL from a worker base_url.

    Expected base forms after :func:`normalize_openai_base_url`:
      - ``…/v1`` → ``…/v1/models``
      - gateway roots without ``/v1`` (e.g. Kilo) → ``…/models``
      - bare host → ``…/v1/models``
    """
    base = normalize_openai_base_url(base_url)
    if not base:
        return "/v1/models"
    if base.endswith("/v1"):
        return base + "/models"
    # Path already looks like a gateway prefix (contains a path segment)
    from urllib.parse import urlparse

    path = (urlparse(base).path or "").strip("/")
    if path:
        # e.g. https://api.kilo.ai/api/gateway → …/gateway/models
        return base.rstrip("/") + "/models"
    return base.rstrip("/") + "/v1/models"


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
