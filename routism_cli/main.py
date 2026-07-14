"""Routism CLI entrypoint — setup, doctor, compose lifecycle, engine pulls."""

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
        description="Routism setup CLI — Ollama engine models + Docker Compose stack",
    )
    p.add_argument(
        "--version",
        action="version",
        version=f"routism-cli {__version__}",
    )
    sub = p.add_subparsers(dest="command", required=True)

    # setup
    s = sub.add_parser("setup", help="Full setup: doctor, Ollama, engine pulls, compose up")
    s.add_argument("--yes", "-y", action="store_true", help="Assume yes for prompts")
    s.add_argument("--dry-run", action="store_true", help="Print actions without changing system")
    s.add_argument("--skip-pull", action="store_true", help="Do not ollama pull engine models")
    s.add_argument("--skip-docker", action="store_true", help="Skip docker compose up")

    sub.add_parser("doctor", help="Check Docker, Ollama, engine models, stack")
    sub.add_parser("start", help="docker compose up --build -d")
    sub.add_parser("stop", help="docker compose down")
    sub.add_parser("restart", help="docker compose restart")
    sub.add_parser("status", help="docker compose ps")

    logs = sub.add_parser("logs", help="docker compose logs")
    logs.add_argument("-f", "--follow", action="store_true", help="Follow log output")
    logs.add_argument("service", nargs="?", default=None, help="Service name (api, ui)")

    sub.add_parser("pull-engine", help="Pull engine models from orch.yaml via Ollama")
    sub.add_parser("open", help=f"Open dashboard ({UI_URL})")
    sub.add_parser("version", help="Print CLI version")

    return p


def cmd_version(_: argparse.Namespace) -> int:
    print(f"routism-cli {__version__}")
    return 0


def cmd_doctor(_: argparse.Namespace) -> int:
    return run_doctor()


def cmd_setup(args: argparse.Namespace) -> int:
    total = 7
    print(f"Routism setup (v{__version__})" + (" [dry-run]" if args.dry_run else ""))

    step(1, total, "Locate repo")
    root = find_repo_root()
    ok(f"repo root: {root}")

    step(2, total, "Preflight checks")
    # Soft doctor — collect issues but continue carefully
    from .docker_ops import check_docker
    from .ollama_ops import check_ollama

    d = check_docker(quiet=False)
    o = check_ollama(quiet=False)

    if not args.skip_docker and (not d.docker_bin or not d.compose_argv or not d.daemon_ok):
        if args.dry_run:
            warn("Docker issues detected (dry-run continues)")
        else:
            raise CliError(
                "Docker is required for setup (use --skip-docker to configure Ollama only).\n"
                "  Fix the Docker issues above and re-run setup."
            )

    step(3, total, "Ensure Ollama")
    ensure_ollama(yes=args.yes, dry_run=args.dry_run)

    step(4, total, "Pull engine models")
    tags = unique_tags(load_engine_tags(root))
    ensure_models(tags, dry_run=args.dry_run, skip_pull=args.skip_pull)

    step(5, total, "Write environment")
    ensure_ollama_base_url(root, yes=args.yes, dry_run=args.dry_run)

    step(6, total, "Start Docker stack")
    if args.skip_docker:
        info("Skipping docker compose (--skip-docker)")
    else:
        compose_ops.up(root, dry_run=args.dry_run, build=True)
        if not args.dry_run:
            if not compose_ops.wait_for_api(timeout_s=180):
                raise CliError(
                    "API did not become healthy in time.\n"
                    "  Check: python3 -m routism_cli logs api"
                )
            compose_ops.smoke_check()
        else:
            info("[dry-run] would wait for API / smoke check")

    step(7, total, "Next steps")
    print()
    ok("Setup complete" + (" (dry-run)" if args.dry_run else ""))
    print()
    print(f"  Dashboard  {UI_URL}")
    print("  API        http://localhost:8000")
    print()
    print(agent_env_snippet())
    print()
    info("Connect providers (Ollama workers, Groq, …) in the dashboard → Providers")
    return 0


def cmd_start(_: argparse.Namespace) -> int:
    root = find_repo_root()
    ensure_ollama_base_url(root, yes=True, dry_run=False)
    compose_ops.up(root, dry_run=False, build=True)
    if not compose_ops.wait_for_api(timeout_s=180):
        raise CliError("API did not become healthy. See: python3 -m routism_cli logs api")
    compose_ops.smoke_check()
    return 0


def cmd_stop(_: argparse.Namespace) -> int:
    root = find_repo_root()
    compose_ops.down(root)
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
    parser = _build_parser()
    args = parser.parse_args(argv)
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
        print(f"error: {e}", file=sys.stderr)
        return e.code
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
