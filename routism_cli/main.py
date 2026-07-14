"""Routism CLI — simple entry: `routism` runs full interactive setup."""

from __future__ import annotations

import argparse
import sys
from typing import List, Optional

from . import __version__
from .config_env import agent_env_snippet, ensure_ollama_base_url
from . import compose as compose_ops
from .doctor import run_doctor
from .engine_models import load_engine_tags, unique_tags
from .ollama_ops import ensure_models, ensure_ollama
from .util import (
    UI_URL,
    CliError,
    confirm,
    find_repo_root,
    info,
    ok,
    open_url,
    step,
    warn,
)


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="routism",
        description=(
            "Routism — self-hosted multi-model orchestration.\n"
            "Run with no arguments for interactive full setup."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  routism                 # interactive setup (default)
  routism setup           # same as above
  routism setup -y        # non-interactive (assume yes)
  routism start|stop      # docker compose up/down
  routism doctor          # health checks only
  routism open            # open dashboard
""",
    )
    p.add_argument(
        "--version",
        action="version",
        version=f"routism {__version__}",
    )
    sub = p.add_subparsers(dest="command")

    s = sub.add_parser("setup", help="Full interactive setup (default if no command)")
    s.add_argument(
        "--yes",
        "-y",
        action="store_true",
        help="Non-interactive: accept defaults / install without asking",
    )
    s.add_argument("--dry-run", action="store_true", help="Show what would run, change nothing")
    s.add_argument("--skip-pull", action="store_true", help="Skip ollama pull of engine models")
    s.add_argument("--skip-docker", action="store_true", help="Skip docker compose up")

    sub.add_parser("doctor", help="Check Docker, Ollama, engine models, stack")
    sub.add_parser("start", help="Start API + UI (docker compose up)")
    sub.add_parser("stop", help="Stop stack (docker compose down)")
    sub.add_parser("restart", help="Restart stack")
    sub.add_parser("status", help="Show container status")

    logs = sub.add_parser("logs", help="Show container logs")
    logs.add_argument("-f", "--follow", action="store_true")
    logs.add_argument("service", nargs="?", default=None)

    sub.add_parser("pull-engine", help="Download engine models via Ollama")
    sub.add_parser("open", help=f"Open dashboard ({UI_URL})")
    sub.add_parser("version", help="Print version")

    return p


def cmd_version(_: argparse.Namespace) -> int:
    print(f"routism {__version__}")
    return 0


def cmd_doctor(_: argparse.Namespace) -> int:
    return run_doctor()


def cmd_setup(args: argparse.Namespace) -> int:
    """Interactive full setup — checks what exists, asks what to do next."""
    dry = args.dry_run
    yes = args.yes
    total = 7

    print()
    print(f"  Routism setup  v{__version__}" + ("  [dry-run]" if dry else ""))
    print("  ────────────────────────────────────────")
    print("  This will check Docker + Ollama, pull engine models,")
    print("  configure .env, and start the API + dashboard.")
    print()

    if not yes and not dry and not confirm("Continue with setup?", default=True):
        info("Cancelled.")
        return 0

    # --- 1. repo ---
    step(1, total, "Find Routism project")
    root = find_repo_root()
    ok(f"Found project at {root}")

    # --- 2. preflight ---
    step(2, total, "Check Docker and Ollama")
    from .docker_ops import check_docker
    from .ollama_ops import check_ollama

    d = check_docker(quiet=False)
    o = check_ollama(quiet=False)

    docker_ok = bool(d.docker_bin and d.compose_argv and d.daemon_ok)
    if not args.skip_docker and not docker_ok:
        if dry:
            warn("Docker not ready (dry-run continues)")
        else:
            print()
            warn("Docker is required to run the API + UI containers.")
            if not d.daemon_ok and d.docker_bin:
                print("  → Start Docker Desktop (or the Docker service), then re-run:  routism")
            else:
                print("  → Install Docker: https://docs.docker.com/get-docker/")
                print("  → Then re-run:  routism")
            if not confirm("Continue setup without Docker? (Ollama/models only)", default=False):
                raise CliError("Docker is not ready. Start Docker and run:  routism")
            args.skip_docker = True

    # --- 3. Ollama ---
    step(3, total, "Ollama (engine models host)")
    if o.binary and o.reachable:
        ok("Ollama is installed and running")
    else:
        if not yes and not dry:
            if not confirm(
                "Ollama is missing or not running. Set it up now?",
                default=True,
            ):
                raise CliError(
                    "Ollama is required for the Conductor engine.\n"
                    "  Install from https://ollama.com/download then run:  routism"
                )
        ensure_ollama(yes=yes or True, dry_run=dry)

    # --- 4. engine models ---
    step(4, total, "Engine models")
    tags = unique_tags(load_engine_tags(root))
    ok(f"Required engine tags: {', '.join(tags)}")

    from .ollama_ops import list_tags, _model_match

    reachable, installed = list_tags()
    missing = [t for t in tags if not _model_match(installed, t)] if reachable else list(tags)

    if not missing:
        ok("All engine models already present — skipping download")
    elif args.skip_pull:
        warn("Skipping model pull (--skip-pull)")
    else:
        if not yes and not dry:
            print()
            info("Engine models can be large (especially qwen2.5:7b).")
            if not confirm(f"Download missing models now? ({', '.join(missing)})", default=True):
                warn("Skipped pulls — Conductor may degrade until models are present")
                args.skip_pull = True
        if not args.skip_pull:
            ensure_models(tags, dry_run=dry, skip_pull=False)

    # --- 5. env ---
    step(5, total, "Write .env for Docker → host Ollama")
    if not yes and not dry:
        info("Sets OLLAMA_BASE_URL so containers can reach Ollama on your machine.")
        if not confirm("Update .env configuration?", default=True):
            warn("Skipped .env update")
        else:
            ensure_ollama_base_url(root, yes=True, dry_run=dry)
    else:
        ensure_ollama_base_url(root, yes=True, dry_run=dry)

    # --- 6. docker ---
    step(6, total, "Start API + UI (Docker)")
    if args.skip_docker:
        info("Skipping Docker stack")
    else:
        if not yes and not dry:
            if not confirm("Build and start Docker (API :8000 + UI :3000)?", default=True):
                warn("Skipped Docker start — run later:  routism start")
                args.skip_docker = True
        if not args.skip_docker:
            compose_ops.up(root, dry_run=dry, build=True)
            if not dry:
                info("Waiting for API to become healthy…")
                if not compose_ops.wait_for_api(timeout_s=180):
                    raise CliError(
                        "API did not become healthy in time.\n"
                        "  Debug:  routism logs api"
                    )
                compose_ops.smoke_check()
            else:
                info("[dry-run] would wait for API health")

    # --- 7. done ---
    step(7, total, "Done")
    print()
    ok("Setup complete" + (" (dry-run)" if dry else ""))
    print()
    print(f"  Dashboard   {UI_URL}")
    print("  API         http://localhost:8000")
    print()
    print(agent_env_snippet())
    print()
    info("In the dashboard: Providers → connect models, then API keys → create a key.")
    print()

    if not dry and not args.skip_docker:
        if yes or confirm("Open the dashboard in your browser now?", default=True):
            open_url(UI_URL)

    print()
    info("Later:  routism start | stop | status | doctor")
    return 0


def cmd_start(_: argparse.Namespace) -> int:
    root = find_repo_root()
    ensure_ollama_base_url(root, yes=True, dry_run=False)
    compose_ops.up(root, dry_run=False, build=True)
    if not compose_ops.wait_for_api(timeout_s=180):
        raise CliError("API did not become healthy. See:  routism logs api")
    compose_ops.smoke_check()
    ok(f"Dashboard {UI_URL}  ·  API http://localhost:8000")
    return 0


def cmd_stop(_: argparse.Namespace) -> int:
    root = find_repo_root()
    compose_ops.down(root)
    ok("Stack stopped")
    return 0


def cmd_restart(_: argparse.Namespace) -> int:
    root = find_repo_root()
    compose_ops.restart(root)
    return 0


def cmd_status(_: argparse.Namespace) -> int:
    root = find_repo_root()
    return compose_ops.ps(root)


def cmd_logs(args: argparse.Namespace) -> int:
    root = find_repo_root()
    return compose_ops.logs(root, follow=args.follow, service=args.service)


def cmd_pull_engine(_: argparse.Namespace) -> int:
    root = find_repo_root()
    ensure_ollama(yes=True, dry_run=False)
    tags = unique_tags(load_engine_tags(root))
    ensure_models(tags, dry_run=False, skip_pull=False)
    return 0


def cmd_open(_: argparse.Namespace) -> int:
    open_url(UI_URL)
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    argv_list = list(sys.argv[1:] if argv is None else argv)

    # Bare `routism` → interactive setup (good UX)
    if not argv_list or argv_list == ["--help"] or argv_list == ["-h"]:
        if not argv_list:
            argv_list = ["setup"]
    elif argv_list[0] not in {
        "setup",
        "doctor",
        "start",
        "stop",
        "restart",
        "status",
        "logs",
        "pull-engine",
        "open",
        "version",
        "--version",
        "-h",
        "--help",
    } and not argv_list[0].startswith("-"):
        # unknown first token — let argparse error
        pass
    elif argv_list[0] in ("-y", "--yes", "--dry-run", "--skip-pull", "--skip-docker"):
        # flags without subcommand → setup
        argv_list = ["setup"] + argv_list

    parser = _build_parser()
    args = parser.parse_args(argv_list)
    if not args.command:
        args = parser.parse_args(["setup"])

    handlers = {
        "version": cmd_version,
        "doctor": cmd_doctor,
        "setup": cmd_setup,
        "start": cmd_start,
        "stop": cmd_stop,
        "restart": cmd_restart,
        "status": cmd_status,
        "logs": cmd_logs,
        "pull-engine": cmd_pull_engine,
        "open": cmd_open,
    }
    try:
        return handlers[args.command](args)
    except CliError as e:
        print(f"\nerror: {e}", file=sys.stderr)
        return e.code
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
