"""Shared helpers for the Routism CLI."""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional, Sequence


COMPOSE_FILE = "docker-compose.yml"
ORCH_MARKER = Path("routism_orch") / "orch.yaml"

UI_URL = "http://localhost:3000"
API_MODELS_URL = "http://127.0.0.1:8000/v1/models"
OLLAMA_TAGS_URL = "http://127.0.0.1:11434/api/tags"
OLLAMA_HOST_URL = "http://127.0.0.1:11434"
DOCKER_HOST_OLLAMA = "http://host.docker.internal:11434"

DOCKER_INSTALL = "https://docs.docker.com/get-docker/"
OLLAMA_DOWNLOAD = "https://ollama.com/download"


class CliError(Exception):
    """Hard failure with a user-facing message."""

    def __init__(self, message: str, code: int = 1) -> None:
        super().__init__(message)
        self.code = code


def ok(msg: str) -> None:
    print(f"  ✓ {msg}", flush=True)


def fail(msg: str) -> None:
    print(f"  ✗ {msg}", file=sys.stderr, flush=True)


def warn(msg: str) -> None:
    print(f"  ! {msg}", flush=True)


def info(msg: str) -> None:
    print(f"  · {msg}", flush=True)


def step(n: int, total: int, title: str) -> None:
    print(f"\n[{n}/{total}] {title}", flush=True)


def which(cmd: str) -> Optional[str]:
    return shutil.which(cmd)


def is_macos() -> bool:
    return platform.system() == "Darwin"


def is_windows() -> bool:
    return platform.system() == "Windows"


def is_linux() -> bool:
    return platform.system() == "Linux"


def confirm(prompt: str, *, yes: bool = False, default: bool = False) -> bool:
    """Ask y/n. ``yes=True`` skips prompt (CI). ``default`` is Enter with empty answer."""
    if yes:
        return True
    if not sys.stdin.isatty():
        return default
    hint = "[Y/n]" if default else "[y/N]"
    try:
        answer = input(f"  ? {prompt} {hint} ").strip().lower()
    except EOFError:
        return default
    if not answer:
        return default
    return answer in ("y", "yes")


def run(
    argv: Sequence[str],
    *,
    cwd: Optional[Path] = None,
    check: bool = True,
    capture: bool = False,
    env: Optional[dict] = None,
    dry_run: bool = False,
) -> subprocess.CompletedProcess:
    display = " ".join(argv)
    if dry_run:
        info(f"[dry-run] {display}")
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    merged = os.environ.copy()
    if env:
        merged.update(env)

    try:
        if capture:
            return subprocess.run(
                list(argv),
                cwd=str(cwd) if cwd else None,
                check=check,
                capture_output=True,
                text=True,
                env=merged,
            )
        return subprocess.run(
            list(argv),
            cwd=str(cwd) if cwd else None,
            check=check,
            env=merged,
        )
    except FileNotFoundError as e:
        raise CliError(f"Command not found: {argv[0]}") from e
    except subprocess.CalledProcessError as e:
        if check:
            detail = ""
            if capture and e.stderr:
                detail = f"\n{e.stderr.strip()}"
            raise CliError(f"Command failed ({e.returncode}): {display}{detail}") from e
        raise


def http_get(
    url: str,
    *,
    timeout: float = 3.0,
) -> tuple[int, str]:
    """Return (status_code, body). status 0 means connection error."""
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return int(resp.status), body
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode("utf-8", errors="replace")
        except Exception:
            body = ""
        return int(e.code), body
    except Exception:
        return 0, ""


def find_repo_root(start: Optional[Path] = None) -> Path:
    """Walk parents from start (or cwd) for docker-compose.yml + routism_orch/orch.yaml."""
    cur = (start or Path.cwd()).resolve()
    for candidate in [cur, *cur.parents]:
        if (candidate / COMPOSE_FILE).is_file() and (candidate / ORCH_MARKER).is_file():
            return candidate
    raise CliError(
        "Could not find Routism repo root.\n"
        f"  Looked for `{COMPOSE_FILE}` and `{ORCH_MARKER}` walking up from {cur}.\n"
        "  cd into the Routism checkout and try again."
    )


def open_url(url: str) -> None:
    system = platform.system()
    try:
        if system == "Darwin":
            subprocess.run(["open", url], check=False)
        elif system == "Windows":
            os.startfile(url)  # type: ignore[attr-defined]
        else:
            opener = which("xdg-open")
            if opener:
                subprocess.run([opener, url], check=False)
            else:
                info(f"Open this URL in your browser: {url}")
                return
        ok(f"Opened {url}")
    except Exception as e:
        warn(f"Could not open browser ({e}). Visit {url}")
