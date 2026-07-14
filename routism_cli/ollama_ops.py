"""Ollama binary detection, install (macOS brew), probe, and model pull."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import List, Optional, Set

from .util import (
    OLLAMA_DOWNLOAD,
    OLLAMA_TAGS_URL,
    CliError,
    confirm,
    fail,
    http_get,
    info,
    is_macos,
    ok,
    run,
    warn,
    which,
)


@dataclass
class OllamaStatus:
    binary: Optional[str] = None
    reachable: bool = False
    models: Set[str] = field(default_factory=set)
    messages: List[str] = field(default_factory=list)


def list_tags(*, timeout: float = 3.0) -> tuple[bool, Set[str]]:
    """Probe Ollama /api/tags. Returns (ok, set of model names)."""
    code, body = http_get(OLLAMA_TAGS_URL, timeout=timeout)
    if code != 200 or not body:
        return False, set()
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return False, set()
    names: Set[str] = set()
    for m in data.get("models") or []:
        name = m.get("name") or m.get("model")
        if name:
            names.add(str(name))
            # Also index without :latest alias noise
            if ":" in name:
                names.add(name.split(":", 1)[0])
    return True, names


def _model_match(installed: Set[str], tag: str) -> bool:
    """True if tag is present in Ollama's tags list (handles :latest aliases)."""
    if tag in installed:
        return True
    base, _, ver = tag.partition(":")
    if not ver:
        return any(n == base or n.startswith(base + ":") for n in installed)
    for n in installed:
        if n == tag or n.startswith(tag + "-") or n.startswith(tag + "@"):
            return True
        if n == f"{base}:{ver}":
            return True
        # installed "qwen2.5:7b" vs required without digest, etc.
        if n.split(":")[0] == base and ":" in n and n.split(":", 1)[1].startswith(ver):
            return True
    return False


def check_ollama(*, quiet: bool = False) -> OllamaStatus:
    status = OllamaStatus()
    binary = which("ollama")
    status.binary = binary
    if not binary:
        msg = (
            "Ollama not found on PATH.\n"
            f"     Install: {OLLAMA_DOWNLOAD}"
            + ("  (or: brew install ollama)" if is_macos() and which("brew") else "")
        )
        status.messages.append(msg)
        if not quiet:
            fail(msg)
    else:
        if not quiet:
            ok(f"ollama found: {binary}")

    reachable, models = list_tags()
    status.reachable = reachable
    status.models = models
    if reachable:
        if not quiet:
            ok(f"Ollama API reachable at {OLLAMA_TAGS_URL} ({len(models)} tag entries)")
    else:
        msg = (
            "Ollama API not reachable at http://127.0.0.1:11434.\n"
            "     Start Ollama (macOS app, or `ollama serve`) and retry."
        )
        status.messages.append(msg)
        if not quiet:
            fail(msg)
    return status


def ensure_ollama(*, yes: bool = False, dry_run: bool = False) -> OllamaStatus:
    """Ensure ollama binary exists and API is up. May brew-install on macOS."""
    status = check_ollama(quiet=False)

    if not status.binary:
        if is_macos() and which("brew"):
            if dry_run:
                info("[dry-run] would run: brew install ollama")
            elif confirm("Install Ollama via Homebrew?", yes=yes):
                info("Installing Ollama with Homebrew…")
                run(["brew", "install", "ollama"], check=True, dry_run=dry_run)
                status.binary = which("ollama")
                if status.binary:
                    ok(f"ollama installed: {status.binary}")
                else:
                    raise CliError(
                        "brew install ollama finished but `ollama` is still not on PATH."
                    )
            else:
                raise CliError(
                    f"Ollama is required for engine models. Install from {OLLAMA_DOWNLOAD}"
                )
        else:
            raise CliError(
                f"Ollama is required for engine models.\n"
                f"  Download: {OLLAMA_DOWNLOAD}"
            )

    if dry_run and not status.reachable:
        info("[dry-run] would wait for Ollama API at http://127.0.0.1:11434")
        return status

    if not status.reachable:
        warn("Ollama is installed but the API is not up yet.")
        info("Start Ollama (open the Ollama app, or run: ollama serve)")
        if not wait_for_ollama(timeout_s=60):
            raise CliError(
                "Timed out waiting for Ollama at http://127.0.0.1:11434.\n"
                "  Start Ollama and re-run: python3 -m routism_cli setup"
            )
        status.reachable = True
        _, status.models = list_tags()
        ok("Ollama API is up")

    return status


def wait_for_ollama(*, timeout_s: float = 60.0, interval_s: float = 2.0) -> bool:
    deadline = time.time() + timeout_s
    info(f"Waiting up to {int(timeout_s)}s for Ollama…")
    while time.time() < deadline:
        ok_flag, _ = list_tags(timeout=2.0)
        if ok_flag:
            return True
        time.sleep(interval_s)
    return False


def pull(tag: str, *, dry_run: bool = False) -> None:
    """Pull a model tag via `ollama pull`, inheriting stdout for progress."""
    binary = which("ollama")
    if not binary and not dry_run:
        raise CliError(f"ollama not found; cannot pull {tag}")
    info(f"Pulling engine model: {tag}")
    run([binary or "ollama", "pull", tag], check=True, dry_run=dry_run)
    if not dry_run:
        ok(f"Pulled {tag}")


def ensure_models(tags: List[str], *, dry_run: bool = False, skip_pull: bool = False) -> None:
    if skip_pull:
        info("Skipping engine model pulls (--skip-pull)")
        return

    reachable, installed = list_tags()
    if not reachable and not dry_run:
        raise CliError("Ollama API not reachable; cannot pull engine models")

    missing = [t for t in tags if not _model_match(installed, t)]
    if not missing:
        ok(f"All engine models present ({', '.join(tags)})")
        return

    for tag in missing:
        pull(tag, dry_run=dry_run)

    if not dry_run:
        _, installed = list_tags()
        still = [t for t in tags if not _model_match(installed, t)]
        if still:
            raise CliError(f"Models still missing after pull: {', '.join(still)}")
        ok("Engine models ready")
