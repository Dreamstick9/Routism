"""Health checks for Docker, Ollama, engine models, and stack endpoints."""

from __future__ import annotations

from pathlib import Path

from . import __version__
from .docker_ops import check_docker
from .engine_models import load_engine_tags
from .ollama_ops import _model_match, check_ollama
from .util import (
    API_MODELS_URL,
    UI_URL,
    fail,
    find_repo_root,
    http_get,
    info,
    ok,
    warn,
)


def run_doctor() -> int:
    print(f"Routism doctor v{__version__}")
    errors = 0
    warnings = 0

    # Repo root
    print("\nRepo")
    try:
        root = find_repo_root()
        ok(f"repo root: {root}")
    except Exception as e:
        fail(str(e))
        return 1

    # Docker
    print("\nDocker")
    d = check_docker(quiet=False)
    if not d.docker_bin or not d.compose_argv or not d.daemon_ok:
        errors += 1

    # Ollama
    print("\nOllama")
    o = check_ollama(quiet=False)
    if not o.binary or not o.reachable:
        errors += 1

    # Engine models
    print("\nEngine models")
    tags = load_engine_tags(root)
    if o.reachable:
        missing = [t for t in tags if not _model_match(o.models, t)]
        if missing:
            warn(f"Missing engine models: {', '.join(missing)}")
            info("Run:  routism pull-engine")
            warnings += 1
        else:
            ok(f"All engine tags present: {', '.join(tags)}")
    else:
        warn("Skipping model inventory (Ollama API down)")
        warnings += 1

    # Config
    print("\nConfig")
    env_path = root / ".env"
    if env_path.is_file():
        ok(".env exists")
        text = env_path.read_text(encoding="utf-8")
        if "OLLAMA_BASE_URL" in text:
            ok("OLLAMA_BASE_URL mentioned in .env")
        else:
            warn("OLLAMA_BASE_URL not set in .env (setup will add it)")
            warnings += 1
    else:
        warn(".env missing (will be created from .env.example on setup)")
        warnings += 1

    compose = root / "docker-compose.yml"
    if compose.is_file():
        ctext = compose.read_text(encoding="utf-8")
        if "host.docker.internal" in ctext and "OLLAMA_BASE_URL" in ctext:
            ok("docker-compose.yml wires OLLAMA_BASE_URL + host-gateway")
        else:
            warn("docker-compose.yml may be missing OLLAMA_BASE_URL / extra_hosts")
            warnings += 1

    # Live endpoints (optional — not hard errors if stack is down)
    print("\nStack endpoints")
    code, _ = http_get(API_MODELS_URL, timeout=2.0)
    if code == 200:
        ok(f"API up: {API_MODELS_URL}")
    else:
        info(f"API not up yet ({API_MODELS_URL}) — run: python3 -m routism_cli start")

    ui_code, _ = http_get(UI_URL, timeout=2.0)
    if ui_code and ui_code < 500:
        ok(f"UI responding: {UI_URL} (HTTP {ui_code})")
    else:
        info(f"UI not up yet ({UI_URL})")

    print()
    if errors:
        fail(f"doctor: {errors} error(s), {warnings} warning(s)")
        return 1
    if warnings:
        warn(f"doctor: OK with {warnings} warning(s)")
        return 0
    ok("doctor: all checks passed")
    return 0
