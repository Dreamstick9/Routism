"""Docker Compose operations for the Routism stack."""

from __future__ import annotations

import time
from pathlib import Path
from typing import List, Optional

from .docker_ops import DockerStatus, check_docker, compose_cmd, require_docker
from .util import (
    API_MODELS_URL,
    UI_URL,
    CliError,
    http_get,
    info,
    ok,
    run,
    warn,
)


def _status_for_compose(*, dry_run: bool = False) -> DockerStatus:
    """Require full Docker health unless dry-run (then CLI + compose binary is enough)."""
    if not dry_run:
        return require_docker()
    status = check_docker(quiet=True)
    if status.compose_argv:
        return status
    # Fall back to a synthetic argv so dry-run can still print the command
    status.compose_argv = ["docker", "compose"]
    warn("Docker Compose not detected; dry-run will show a generic compose command")
    return status


def up(repo_root: Path, *, dry_run: bool = False, build: bool = True) -> None:
    status = _status_for_compose(dry_run=dry_run)
    args = ["up", "--build", "-d"] if build else ["up", "-d"]
    cmd = compose_cmd(status, *args)
    info(f"Starting stack: {' '.join(cmd)}")
    run(cmd, cwd=repo_root, check=True, dry_run=dry_run)
    if not dry_run:
        ok("docker compose up finished")


def down(repo_root: Path, *, dry_run: bool = False) -> None:
    status = _status_for_compose(dry_run=dry_run)
    cmd = compose_cmd(status, "down")
    info(f"Stopping stack: {' '.join(cmd)}")
    run(cmd, cwd=repo_root, check=True, dry_run=dry_run)
    if not dry_run:
        ok("Stack stopped")


def restart(repo_root: Path, *, dry_run: bool = False) -> None:
    status = _status_for_compose(dry_run=dry_run)
    cmd = compose_cmd(status, "restart")
    info(f"Restarting stack: {' '.join(cmd)}")
    run(cmd, cwd=repo_root, check=True, dry_run=dry_run)
    if not dry_run:
        ok("Stack restarted")


def ps(repo_root: Path) -> int:
    status = require_docker()
    cmd = compose_cmd(status, "ps")
    cp = run(cmd, cwd=repo_root, check=False)
    return cp.returncode


def logs(
    repo_root: Path,
    *,
    follow: bool = False,
    service: Optional[str] = None,
) -> int:
    status = require_docker()
    args: List[str] = ["logs"]
    if follow:
        args.append("-f")
    # sensible tail so first view is useful
    args.extend(["--tail", "200"])
    if service:
        args.append(service)
    cmd = compose_cmd(status, *args)
    cp = run(cmd, cwd=repo_root, check=False)
    return cp.returncode


def wait_for_api(*, timeout_s: float = 120.0, interval_s: float = 2.0) -> bool:
    """Poll GET /v1/models until HTTP 200."""
    info(f"Waiting up to {int(timeout_s)}s for API at {API_MODELS_URL}…")
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        code, _ = http_get(API_MODELS_URL, timeout=3.0)
        if code == 200:
            ok(f"API healthy: {API_MODELS_URL}")
            return True
        time.sleep(interval_s)
    return False


def smoke_check() -> None:
    code, body = http_get(API_MODELS_URL, timeout=5.0)
    if code != 200:
        raise CliError(
            f"Smoke check failed: {API_MODELS_URL} returned HTTP {code or 'connection error'}"
        )
    ok(f"Smoke check passed (GET /v1/models → {code})")
    info(f"Dashboard: {UI_URL}")
    info(f"API:       http://localhost:8000")
