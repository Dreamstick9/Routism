#!/usr/bin/env python3
"""Unit tests for Docker host rewrite + management auth helpers (shipped modules)."""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from routism.host_reach import (  # noqa: E402
    DOCKER_HOST_GATEWAY,
    api_runs_in_docker,
    client_is_loopback_host,
    client_is_private_host,
    management_client_allowed,
    rewrite_loopback_url_for_container,
)
from routism.security_ssrf import SSRFBlocked, validate_worker_base_url  # noqa: E402


def test_rewrite_localhost_when_docker() -> None:
    out = rewrite_loopback_url_for_container(
        "http://localhost:11434/v1", in_docker=True
    )
    assert out == f"http://{DOCKER_HOST_GATEWAY}:11434/v1"
    out2 = rewrite_loopback_url_for_container(
        "http://127.0.0.1:1234", in_docker=True
    )
    assert out2 == f"http://{DOCKER_HOST_GATEWAY}:1234"


def test_rewrite_noop_when_not_docker() -> None:
    raw = "http://localhost:11434/v1"
    assert rewrite_loopback_url_for_container(raw, in_docker=False) == raw


def test_rewrite_leaves_remote() -> None:
    raw = "https://api.groq.com/openai/v1"
    assert rewrite_loopback_url_for_container(raw, in_docker=True) == raw


def test_api_runs_in_docker_env(monkeypatch_env=None) -> None:
    # Without env / .dockerenv — not docker (or may be true if test runs in container)
    os.environ.pop("ROUTISM_IN_DOCKER", None)
    forced = api_runs_in_docker(force=True)
    assert forced is True
    assert api_runs_in_docker(force=False) is False


def test_management_allows_loopback_without_key() -> None:
    assert management_client_allowed(
        "127.0.0.1", management_key=None, bearer_ok=False, open_local=True
    )
    assert management_client_allowed(
        "::1", management_key=None, bearer_ok=False, open_local=True
    )


def test_management_allows_docker_bridge_when_open_local() -> None:
    # Typical Docker published-port source IP
    assert management_client_allowed(
        "172.18.0.1", management_key=None, bearer_ok=False, open_local=True
    )
    assert client_is_private_host("172.18.0.1")


def test_management_denies_public_without_key() -> None:
    assert not management_client_allowed(
        "8.8.8.8", management_key=None, bearer_ok=False, open_local=True
    )
    assert not management_client_allowed(
        "203.0.113.10", management_key=None, bearer_ok=False, open_local=False
    )


def test_management_key_requires_bearer() -> None:
    assert not management_client_allowed(
        "8.8.8.8", management_key="secret", bearer_ok=False, open_local=True
    )
    assert management_client_allowed(
        "8.8.8.8", management_key="secret", bearer_ok=True, open_local=True
    )


def test_ssrf_allows_host_docker_internal_http() -> None:
    os.environ["ROUTISM_SSRF_RESOLVE"] = "0"
    out = validate_worker_base_url("http://host.docker.internal:11434/v1")
    assert "host.docker.internal" in out


def test_ssrf_still_blocks_private_non_gateway() -> None:
    os.environ["ROUTISM_SSRF_RESOLVE"] = "0"
    os.environ["ROUTISM_ALLOW_PRIVATE_URLS"] = "0"
    try:
        validate_worker_base_url("http://10.0.0.5/v1")
        raise AssertionError("should block")
    except SSRFBlocked:
        pass


def test_client_loopback_helpers() -> None:
    assert client_is_loopback_host("127.0.0.1")
    assert not client_is_loopback_host("172.17.0.2")
    assert client_is_private_host("10.0.0.5")


if __name__ == "__main__":
    # Minimal runner without pytest
    fails = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  PASS  {name}")
            except Exception as e:
                fails += 1
                print(f"  FAIL  {name}: {type(e).__name__}: {e}")
    raise SystemExit(1 if fails else 0)
