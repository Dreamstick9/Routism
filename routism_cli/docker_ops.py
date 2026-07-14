"""Docker / Docker Compose detection and health checks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from .util import DOCKER_INSTALL, CliError, fail, info, ok, run, which


@dataclass
class DockerStatus:
    docker_bin: Optional[str] = None
    compose_argv: Optional[List[str]] = None
    daemon_ok: bool = False
    messages: Optional[List[str]] = None

    def __post_init__(self) -> None:
        if self.messages is None:
            self.messages = []


def _probe_compose(docker_bin: str) -> Optional[List[str]]:
    """Prefer `docker compose` (v2 plugin), fall back to `docker-compose`."""
    try:
        cp = run(
            [docker_bin, "compose", "version"],
            check=False,
            capture=True,
        )
        if cp.returncode == 0:
            return [docker_bin, "compose"]
    except CliError:
        pass

    dc = which("docker-compose")
    if dc:
        try:
            cp = run([dc, "version"], check=False, capture=True)
            if cp.returncode == 0:
                return [dc]
        except CliError:
            pass
    return None


def check_docker(*, quiet: bool = False) -> DockerStatus:
    status = DockerStatus()
    docker_bin = which("docker")
    if not docker_bin:
        msg = (
            "Docker CLI not found on PATH.\n"
            f"     Install Docker Desktop: {DOCKER_INSTALL}"
        )
        status.messages.append(msg)
        if not quiet:
            fail(msg)
        return status

    status.docker_bin = docker_bin
    if not quiet:
        ok(f"docker found: {docker_bin}")

    compose = _probe_compose(docker_bin)
    if not compose:
        msg = (
            "Docker Compose not found (`docker compose` or `docker-compose`).\n"
            f"     Install Docker Desktop (includes Compose): {DOCKER_INSTALL}"
        )
        status.messages.append(msg)
        if not quiet:
            fail(msg)
        return status

    status.compose_argv = compose
    label = " ".join(compose)
    if not quiet:
        ok(f"compose found: {label}")

    try:
        cp = run([docker_bin, "info"], check=False, capture=True)
        if cp.returncode == 0:
            status.daemon_ok = True
            if not quiet:
                ok("Docker daemon is reachable")
        else:
            err = (cp.stderr or cp.stdout or "").strip().splitlines()
            tail = err[-1] if err else "daemon not responding"
            msg = (
                f"Docker daemon not reachable: {tail}\n"
                "     Start Docker Desktop (or the docker service) and retry."
            )
            status.messages.append(msg)
            if not quiet:
                fail(msg)
    except CliError as e:
        status.messages.append(str(e))
        if not quiet:
            fail(str(e))

    return status


def require_docker() -> DockerStatus:
    status = check_docker(quiet=False)
    if not status.docker_bin:
        raise CliError(
            f"Docker is required. Install from {DOCKER_INSTALL}",
            code=1,
        )
    if not status.compose_argv:
        raise CliError(
            f"Docker Compose is required. Install from {DOCKER_INSTALL}",
            code=1,
        )
    if not status.daemon_ok:
        raise CliError(
            "Docker daemon is not running. Start Docker Desktop and retry.",
            code=1,
        )
    return status


def compose_cmd(status: DockerStatus, *args: str) -> List[str]:
    if not status.compose_argv:
        raise CliError("Docker Compose not available")
    return [*status.compose_argv, *args]
