"""Docker host reachability helpers for local LLM servers and management auth.

When the API runs in a container, ``localhost`` / ``127.0.0.1`` in user-facing
worker URLs point at the *container*, not the host machine where Ollama / LM
Studio / MLX typically run. These helpers rewrite loopback hosts to the Docker
host gateway and decide whether a management client is allowed without a key.

All decision functions are pure with respect to injected flags so unit tests do
not need a live Docker daemon.
"""
from __future__ import annotations

import ipaddress
import os
from pathlib import Path
from urllib.parse import urlparse, urlunparse

# Hostname Docker Desktop / compose extra_hosts use for the host machine.
DOCKER_HOST_GATEWAY = "host.docker.internal"

_LOOPBACK_HOSTS = frozenset(
    {
        "localhost",
        "localhost.localdomain",
        "127.0.0.1",
        "::1",
        "[::1]",
    }
)

_DOCKER_GATEWAY_HOSTS = frozenset(
    {
        DOCKER_HOST_GATEWAY,
        "gateway.docker.internal",
    }
)


def _env_flag(name: str, default: str = "0") -> bool:
    return os.environ.get(name, default).strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def api_runs_in_docker(*, force: bool | None = None) -> bool:
    """True when this process should treat outbound loopback as container-local.

    Detection order:
    1. Explicit ``force`` (tests)
    2. ``ROUTISM_IN_DOCKER=1`` (compose sets this)
    3. Presence of ``/.dockerenv``
    """
    if force is not None:
        return bool(force)
    if _env_flag("ROUTISM_IN_DOCKER", "0"):
        return True
    try:
        return Path("/.dockerenv").is_file()
    except OSError:
        return False


def open_local_enabled() -> bool:
    """ROUTISM_OPEN_LOCAL defaults to on (local dashboard without secrets)."""
    return _env_flag("ROUTISM_OPEN_LOCAL", "1")


def is_loopback_hostname(host: str | None) -> bool:
    if not host:
        return False
    h = host.strip().lower().strip("[]")
    if h in _LOOPBACK_HOSTS or h in ("localhost", "127.0.0.1", "::1"):
        return True
    try:
        return ipaddress.ip_address(h).is_loopback
    except ValueError:
        return False


def is_docker_gateway_hostname(host: str | None) -> bool:
    if not host:
        return False
    return host.strip().lower().strip("[]") in _DOCKER_GATEWAY_HOSTS


def rewrite_loopback_url_for_container(
    url: str,
    *,
    in_docker: bool | None = None,
    gateway: str = DOCKER_HOST_GATEWAY,
) -> str:
    """Rewrite loopback host in ``url`` to the Docker host gateway when in Docker.

    Leaves non-loopback URLs unchanged. Empty/invalid input returned as-is.
    When not in Docker, returns the original URL.

    Examples
    --------
    >>> rewrite_loopback_url_for_container("http://localhost:11434/v1", in_docker=True)
    'http://host.docker.internal:11434/v1'
    >>> rewrite_loopback_url_for_container("http://localhost:11434/v1", in_docker=False)
    'http://localhost:11434/v1'
    """
    raw = (url or "").strip()
    if not raw:
        return url
    docker = api_runs_in_docker(force=in_docker) if in_docker is not None else api_runs_in_docker()
    if not docker:
        return raw

    # Support bare host:port
    to_parse = raw if "://" in raw else f"http://{raw}"
    try:
        parts = urlparse(to_parse)
    except Exception:
        return raw
    host = parts.hostname
    if not is_loopback_hostname(host):
        return raw

    # Rebuild netloc with gateway, preserving port and userinfo absence
    port = parts.port
    new_host = gateway
    if port is not None:
        netloc = f"{new_host}:{port}"
    else:
        netloc = new_host
    rebuilt = urlunparse(
        (
            parts.scheme or "http",
            netloc,
            parts.path or "",
            parts.params,
            parts.query,
            parts.fragment,
        )
    )
    # If caller passed host:port without scheme, strip scheme we added only when
    # original had no scheme — keep full URL for pool/OpenAI bases.
    if "://" not in raw:
        # Return gateway form with scheme for consistency (callers expect URLs)
        return rebuilt
    return rebuilt


def _coerce_ip(client_host: str | None):
    """Parse client host; unwrap IPv4-mapped IPv6 (``::ffff:127.0.0.1``)."""
    if not client_host:
        return None
    h = client_host.strip().lower().strip("[]")
    try:
        ip = ipaddress.ip_address(h)
    except ValueError:
        return None
    # Docker / some stacks present loopback as IPv4-mapped IPv6
    mapped = getattr(ip, "ipv4_mapped", None)
    if mapped is not None:
        return mapped
    return ip


def client_is_loopback_host(client_host: str | None) -> bool:
    """True if the HTTP client address is loopback."""
    if not client_host:
        return False
    h = client_host.strip().lower().strip("[]")
    if h in ("127.0.0.1", "::1", "localhost", "localhost.localdomain"):
        return True
    ip = _coerce_ip(client_host)
    if ip is None:
        return False
    return bool(ip.is_loopback)


def client_is_private_host(client_host: str | None) -> bool:
    """True if client is RFC1918 / ULA private (typical Docker bridge source)."""
    ip = _coerce_ip(client_host)
    if ip is None:
        return False
    if ip.is_loopback:
        return False
    return bool(ip.is_private)


def host_header_is_local(host_header: str | None) -> bool:
    """True if HTTP Host targets the local machine (browser → localhost:8000).

    Docker Desktop + VPN/WARP often presents a non-loopback client IP even when
    the user opens http://localhost:8000. Trusting a local Host header (only
    when open_local is on) restores the stock local-dashboard UX. For public
    exposure, set MANAGEMENT_API_KEY (and ROUTISM_REQUIRE_API_KEY).
    """
    if not host_header:
        return False
    h = host_header.split("/", 1)[0].split(":", 1)[0].strip().lower().strip("[]")
    if h in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):
        return True
    if h.endswith(".localhost"):
        return True
    return False


def management_client_allowed(
    client_host: str | None,
    *,
    management_key: str | None,
    bearer_ok: bool = False,
    open_local: bool | None = None,
    host_header: str | None = None,
) -> bool:
    """Whether a management mutation is allowed for this client.

    Rules (stock Docker Desktop / local dashboard):
    - If ``management_key`` is non-empty: require ``bearer_ok``.
    - If no key: allow loopback client always.
    - If no key and open_local (default on):
        - private RFC1918 clients (Docker bridge), OR
        - requests whose Host header is localhost / 127.0.0.1
          (covers VPN/WARP source IPs when the user still targets localhost).
    - Public Host + public client without a key → denied.
    """
    key = (management_key or "").strip()
    if key:
        return bool(bearer_ok)
    if client_is_loopback_host(client_host):
        return True
    ol = open_local_enabled() if open_local is None else bool(open_local)
    if not ol:
        return False
    if client_is_private_host(client_host):
        return True
    if host_header_is_local(host_header):
        return True
    return False


def connection_refused_hint(url: str, *, in_docker: bool | None = None) -> str:
    """Extra guidance when a local server is unreachable."""
    docker = api_runs_in_docker(force=in_docker) if in_docker is not None else api_runs_in_docker()
    base = (
        "Is the local server running on this machine? "
        "Start Ollama / LM Studio / MLX, then retry."
    )
    if docker:
        return (
            f"{base} "
            "The API is in Docker: host loopback is rewritten to "
            f"{DOCKER_HOST_GATEWAY} automatically. If it still fails, confirm "
            "the app is listening on the host and the port matches."
        )
    return base
