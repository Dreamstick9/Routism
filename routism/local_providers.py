"""Local OpenAI-compatible LLM one-click providers (Ollama, LM Studio, MLX).

Discover → list models → add-to-pool. No API key for these loopback paths.
Host defaults can be overridden with env vars (same spirit as OLLAMA_HOST).
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import urlparse

import httpx

from .health_probe import is_healthy_status
from .host_reach import (
    connection_refused_hint,
    rewrite_loopback_url_for_container,
)


@dataclass(frozen=True)
class LocalProviderSpec:
    """One local server type the dashboard can one-click connect."""

    id: str  # ollama | lmstudio | mlx
    display_name: str
    env_host: str
    default_native_base: str  # without trailing slash, may or may not include /v1
    openai_base_url: str  # OpenAI-compat base for pool worker (…/v1)
    tags: tuple[str, ...]
    # How to list models
    list_kind: str  # "ollama_tags" | "openai_models"


LOCAL_PROVIDER_SPECS: dict[str, LocalProviderSpec] = {
    "ollama": LocalProviderSpec(
        id="ollama",
        display_name="Ollama",
        env_host="OLLAMA_HOST",
        default_native_base="http://localhost:11434",
        openai_base_url="http://localhost:11434/v1",
        tags=("local", "ollama", "free"),
        list_kind="ollama_tags",
    ),
    "lmstudio": LocalProviderSpec(
        id="lmstudio",
        display_name="LM Studio",
        env_host="LM_STUDIO_HOST",
        default_native_base="http://localhost:1234",
        openai_base_url="http://localhost:1234/v1",
        tags=("local", "lmstudio", "free"),
        list_kind="openai_models",
    ),
    "mlx": LocalProviderSpec(
        id="mlx",
        display_name="MLX",
        env_host="MLX_HOST",
        # Common defaults: mlx_lm.server / openai-compatible MLX servers on 8080
        default_native_base="http://localhost:8080",
        openai_base_url="http://localhost:8080/v1",
        tags=("local", "mlx", "free"),
        list_kind="openai_models",
    ),
}


def get_local_spec(provider_id: str) -> LocalProviderSpec | None:
    return LOCAL_PROVIDER_SPECS.get((provider_id or "").strip().lower())


def normalize_local_base(user_base: str | None, *, default: str) -> str:
    """Normalize a user/env host string into a scheme://host:port root (no trailing /v1).

    Accepts:
      - full URL: ``http://localhost:6969`` or ``http://127.0.0.1:6969/v1``
      - host:port: ``localhost:6969``
      - port only: ``6969`` or ``:6969`` → ``http://localhost:6969``
    """
    raw = (user_base or "").strip()
    if not raw:
        raw = default
    raw = raw.rstrip("/")
    # Port-only forms
    if raw.startswith(":") and raw[1:].isdigit():
        raw = f"http://localhost{raw}"
    elif raw.isdigit():
        raw = f"http://localhost:{raw}"
    elif "://" not in raw:
        raw = f"http://{raw}"
    # Drop trailing /v1 so callers can re-append for OpenAI path
    if raw.endswith("/v1"):
        raw = raw[:-3].rstrip("/")
    return raw


def resolve_native_base(spec: LocalProviderSpec, user_base: str | None = None) -> str:
    """Native server root (no forced /v1) from user override, env, or default.

    When the API runs in Docker, loopback hosts are rewritten to
    ``host.docker.internal`` so host Ollama / LM Studio / MLX are reachable.
    """
    if user_base and str(user_base).strip():
        base = normalize_local_base(user_base, default=spec.default_native_base)
    else:
        env_val = (os.environ.get(spec.env_host) or "").strip()
        base = normalize_local_base(env_val or None, default=spec.default_native_base)
    return rewrite_loopback_url_for_container(base)


def resolve_openai_base(spec: LocalProviderSpec, user_base: str | None = None) -> str:
    """OpenAI-compatible base_url for pool workers (always ends with /v1)."""
    native = resolve_native_base(spec, user_base)
    if native.endswith("/v1"):
        return native
    return native + "/v1"


def _parse_openai_models_payload(data: Any) -> list[str]:
    if isinstance(data, dict) and "data" in data:
        out: list[str] = []
        for m in data.get("data") or []:
            if isinstance(m, dict) and m.get("id"):
                out.append(str(m["id"]))
            elif isinstance(m, str):
                out.append(m)
        return out
    if isinstance(data, dict) and "models" in data:
        out = []
        for m in data.get("models") or []:
            if isinstance(m, dict):
                name = m.get("name") or m.get("id") or m.get("model")
                if name:
                    out.append(str(name).removeprefix("models/"))
            elif isinstance(m, str):
                out.append(m)
        return out
    if isinstance(data, list):
        out = []
        for m in data:
            if isinstance(m, dict) and m.get("id"):
                out.append(str(m["id"]))
            elif isinstance(m, str):
                out.append(m)
        return out
    return []


def _parse_ollama_tags(data: Any) -> list[str]:
    if not isinstance(data, dict):
        return []
    models = data.get("models") or []
    names: list[str] = []
    for m in models:
        if isinstance(m, dict) and m.get("name"):
            names.append(str(m["name"]))
        elif isinstance(m, str):
            names.append(m)
    return names


def discover_local_models(
    provider_id: str,
    *,
    base_url: str | None = None,
    api_key: str | None = None,
    timeout_s: float = 5.0,
    reserved_model_names: set[str] | None = None,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    """Discover models for a local one-click provider.

    ``base_url`` is an optional user override (host, port, or full URL). When
    omitted, env + defaults apply. ``api_key`` is optional Bearer token for
    local servers that require auth (some oMLX / gated OpenAI-compat servers).

    Returns shape::
        {running: bool, base_url?: str, openai_base_url?: str, models?: list[str],
         provider?: str, error?: str}
    """
    spec = get_local_spec(provider_id)
    if spec is None:
        return {
            "running": False,
            "error": f"unknown local provider {provider_id!r}; "
            f"expected one of {sorted(LOCAL_PROVIDER_SPECS)}",
        }

    native = resolve_native_base(spec, base_url)
    openai_base = resolve_openai_base(spec, base_url)
    reserved = reserved_model_names or set()
    headers: dict[str, str] = {}
    key = (api_key or "").strip()
    if key:
        headers["Authorization"] = f"Bearer {key}"

    if spec.list_kind == "ollama_tags":
        # Native Ollama API (not under /v1)
        host = native[:-3] if native.endswith("/v1") else native
        url = f"{host}/api/tags"
        parse: Callable[[Any], list[str]] = _parse_ollama_tags
    else:
        host = native
        if host.endswith("/v1"):
            url = host + "/models"
        else:
            url = host + "/v1/models"
        parse = _parse_openai_models_payload

    own_client = client is None
    try:
        if client is None:
            client = httpx.Client(timeout=timeout_s)
        r = client.get(url, headers=headers or None)
        if not is_healthy_status(r.status_code):
            hint = (
                f"{spec.display_name} returned HTTP {r.status_code} from {url}. "
                f"Check host/port"
            )
            if r.status_code in (401, 403):
                hint += " and API key (some local servers require a key)"
            else:
                hint += " (yours may not be the default)"
            hint += "."
            return {
                "running": False,
                "provider": spec.id,
                "base_url": openai_base,
                "openai_base_url": openai_base,
                "error": hint,
            }
        try:
            data = r.json()
        except Exception as e:  # noqa: BLE001
            return {
                "running": False,
                "provider": spec.id,
                "base_url": openai_base,
                "error": f"invalid JSON from {url}: {type(e).__name__}: {e}",
            }
        models = [m for m in parse(data) if m and m not in reserved]
        return {
            "running": True,
            "provider": spec.id,
            "base_url": openai_base,
            "openai_base_url": openai_base,
            "models": models,
        }
    except Exception as e:  # noqa: BLE001
        hint = connection_refused_hint(native)
        return {
            "running": False,
            "provider": spec.id,
            "base_url": openai_base,
            "openai_base_url": openai_base,
            "error": (
                f"{spec.display_name} not reachable at {native}. {hint} "
                f"({type(e).__name__}: {e})"
            ),
        }
    finally:
        if own_client and client is not None:
            client.close()


def worker_id_for_local(provider_id: str, model: str) -> str:
    safe = "".join(c if c.isalnum() or c in "_-." else "_" for c in model)
    safe = safe.replace(".", "_").replace("-", "_")
    return f"{provider_id}_{safe}"


def pool_worker_payload(
    provider_id: str,
    model: str,
    *,
    base_url: str | None = None,
) -> dict[str, Any]:
    """Shape accepted by POST /v1/management/pool for a local one-click add."""
    spec = get_local_spec(provider_id)
    if spec is None:
        raise ValueError(f"unknown local provider {provider_id!r}")
    return {
        "id": worker_id_for_local(provider_id, model),
        "provider": spec.id,
        "base_url": resolve_openai_base(spec, base_url),
        "model": model,
        "tags": list(spec.tags),
    }


def is_loopback_base_url(url: str) -> bool:
    """True if URL targets localhost / loopback (for SSRF policy helpers)."""
    try:
        host = (urlparse(url).hostname or "").lower().strip("[]")
    except Exception:
        return False
    if host in ("localhost", "localhost.localdomain"):
        return True
    try:
        import ipaddress

        ip = ipaddress.ip_address(host)
        return bool(ip.is_loopback)
    except ValueError:
        return False
