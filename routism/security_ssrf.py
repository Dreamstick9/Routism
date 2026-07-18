"""SSRF guards for user-supplied worker ``base_url`` values.

Practical baseline (not a formal security audit):
- Block link-local / cloud-metadata ranges (e.g. 169.254.169.254).
- Block private/reserved non-loopback ranges unless ``ROUTISM_ALLOW_PRIVATE_URLS=1``.
- **Always allow loopback** (localhost / 127.0.0.1 / ::1) over http and https so
  local one-click providers (Ollama, LM Studio, MLX) work without env flags.
- Allow ``https`` for remote hosts; ``http`` only for loopback/localhost.
- Optionally resolve hostnames and re-check the resulting IPs.

Env knobs:
- ``ROUTISM_ALLOW_PRIVATE_URLS`` — default ``0`` (block RFC1918 / ULA / etc.)
- ``ALLOW_LOCAL_HTTP`` — legacy; loopback is always allowed. Kept for docs/compat.
- ``ROUTISM_SSRF_RESOLVE`` — default ``1``; when ``0``, skip DNS resolution
  (hostname still validated as IP if literal).
"""
from __future__ import annotations

import ipaddress
import os
import socket
from urllib.parse import urlparse

# AWS / GCP / Azure classic metadata address (IPv4 link-local).
_METADATA_V4 = ipaddress.ip_address("169.254.169.254")
# Common IPv6 metadata / link-local patterns we always reject.
_METADATA_V6_NETS = (
    ipaddress.ip_network("fe80::/10"),  # IPv6 link-local
    ipaddress.ip_network("fd00:ec2::/32"),  # AWS IMDS v2 IPv6 (where used)
)


class SSRFBlocked(ValueError):
    """Raised when a URL is rejected as a potential SSRF target."""


def _env_flag(name: str, default: str = "0") -> bool:
    return os.environ.get(name, default).strip().lower() in ("1", "true", "yes", "on")


def allow_private_urls() -> bool:
    return _env_flag("ROUTISM_ALLOW_PRIVATE_URLS", "0")


def allow_local_http() -> bool:
    """Legacy flag. Loopback is always permitted; this remains for callers/tests."""
    return _env_flag("ALLOW_LOCAL_HTTP", "0")


def _resolve_enabled() -> bool:
    return _env_flag("ROUTISM_SSRF_RESOLVE", "1")


def _is_localhost_name(host: str) -> bool:
    h = host.lower().rstrip(".").strip("[]")
    return h in ("localhost", "localhost.localdomain")


def _is_docker_host_gateway_name(host: str) -> bool:
    """Docker Desktop / compose host gateway — treat like loopback for local LLMs."""
    h = host.lower().rstrip(".").strip("[]")
    return h in ("host.docker.internal", "gateway.docker.internal")


def _parse_ip(host: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    h = host.strip("[]")
    try:
        return ipaddress.ip_address(h)
    except ValueError:
        return None


def _ip_block_reason(
    ip: ipaddress.IPv4Address | ipaddress.IPv6Address,
    *,
    allow_private: bool,
    allow_loopback: bool,
) -> str | None:
    """Return a human reason if ``ip`` is blocked, else None."""
    if ip == _METADATA_V4:
        return "cloud metadata address (169.254.169.254)"
    for net in _METADATA_V6_NETS:
        if ip in net:
            return f"blocked metadata/link-local range ({net})"

    if ip.is_unspecified:
        return "unspecified address (0.0.0.0 / ::)"
    if ip.is_multicast:
        return "multicast address"
    if ip.is_link_local:
        return "link-local address"
    if ip.is_loopback:
        if not allow_loopback:
            return "loopback address blocked"
        return None
    # CGNAT / shared address space — treat as private for SSRF purposes.
    if isinstance(ip, ipaddress.IPv4Address) and ip in ipaddress.ip_network("100.64.0.0/10"):
        if not allow_private:
            return "shared/CGNAT address (100.64.0.0/10)"
        return None
    if ip.is_private:
        if not allow_private:
            return "private address (set ROUTISM_ALLOW_PRIVATE_URLS=1 to allow)"
        return None
    # IPv6 unique-local (fc00::/7) is covered by is_private in modern Python.
    if getattr(ip, "is_reserved", False) and not allow_private:
        # Be careful: some public space was historically "reserved". Only block
        # clearly non-routable reserved when we also disallow private.
        if ip.is_reserved and not ip.is_global:
            return "reserved/non-global address"
    return None


def _resolve_ips(host: str) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    """Resolve hostname to IPs. Empty list if resolution fails or disabled."""
    if not _resolve_enabled():
        return []
    h = host.strip("[]")
    ips: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    try:
        infos = socket.getaddrinfo(h, None, type=socket.SOCK_STREAM)
    except socket.gaierror:
        return []
    seen: set[str] = set()
    for info in infos:
        sockaddr = info[4]
        addr = sockaddr[0]
        if addr in seen:
            continue
        seen.add(addr)
        try:
            ips.append(ipaddress.ip_address(addr))
        except ValueError:
            continue
    return ips


def validate_worker_base_url(url: str) -> str:
    """Validate a worker ``base_url`` against SSRF rules.

    Returns the stripped URL on success.
    Raises ``SSRFBlocked`` (subclass of ``ValueError``) on rejection.

    Loopback (localhost / 127.0.0.1 / ::1) is **always** allowed over http and
    https so Ollama / LM Studio / MLX one-click works out of the box. Non-loopback
    private ranges still require ``ROUTISM_ALLOW_PRIVATE_URLS=1``. Metadata and
    link-local addresses are always blocked.
    """
    if url is None or not str(url).strip():
        raise SSRFBlocked("base_url is required")

    raw = str(url).strip()
    parsed = urlparse(raw)
    scheme = (parsed.scheme or "").lower()
    host = parsed.hostname

    if scheme not in ("http", "https"):
        raise SSRFBlocked(f"scheme {scheme!r} not allowed (use https, or http for localhost only)")

    if not host:
        raise SSRFBlocked("base_url must include a hostname")

    if parsed.username is not None or parsed.password is not None:
        raise SSRFBlocked("credentials in base_url are not allowed")

    allow_private = allow_private_urls()
    is_local_name = _is_localhost_name(host)
    is_docker_gw = _is_docker_host_gateway_name(host)
    literal_ip = _parse_ip(host)

    # Loopback is always permitted (local LLM servers on the laptop).
    allow_loopback = True

    # Scheme rules: http only for localhost/loopback / Docker host gateway
    # (API-in-Docker → host Ollama). Private non-loopback still uses https + flag.
    if scheme == "http":
        if literal_ip is not None:
            if not literal_ip.is_loopback:
                raise SSRFBlocked("http is only allowed for loopback addresses (localhost)")
        elif not is_local_name and not is_docker_gw:
            raise SSRFBlocked("http is only allowed for localhost / loopback")

    if literal_ip is not None:
        reason = _ip_block_reason(
            literal_ip, allow_private=allow_private, allow_loopback=allow_loopback
        )
        if reason:
            raise SSRFBlocked(f"base_url blocked: {reason}")
    elif is_local_name or is_docker_gw:
        # localhost or host.docker.internal always OK for local LLM access
        pass
    else:
        # Remote hostname: resolve and check each A/AAAA record.
        for ip in _resolve_ips(host):
            reason = _ip_block_reason(
                ip, allow_private=allow_private, allow_loopback=False
            )
            if reason:
                raise SSRFBlocked(f"base_url host resolves to blocked address ({ip}): {reason}")

    return raw
