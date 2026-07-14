#!/usr/bin/env python3
"""Public-safety gate: no secrets / personal absolute paths in ship surface.

Drives real filesystem scan of the repo (excluding gitignored product-local paths).
Fails if high-risk patterns appear in files that would be published.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SKIP_DIRS = frozenset(
    {
        "node_modules",
        ".next",
        "__pycache__",
        ".git",
        "venv",
        ".venv",
        ".pytest_cache",
        "data",
        "archive",
        "routism_legacy",
        "eval_results",
        ".agents",
        ".claude",
        ".commandcode",
        ".opencode",
        "$SCRATCH",
    }
)

SKIP_NAMES = frozenset(
    {
        ".DS_Store",
        "routism.yaml",
        ".env",
        ".env.local",
        "phase2_results.json",
        "_p5b_hcache.json",
        "tsconfig.tsbuildinfo",
        "local_fernet.key",
        "bootstrap_key.txt",
        "api_keys.db",
    }
)

# High-risk secrets (no machine identity embedded here)
SECRET_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("openai_sk_live", re.compile(r"sk-(?:proj-)?[A-Za-z0-9]{32,}")),
    ("gsk_", re.compile(r"gsk_[A-Za-z0-9]{20,}")),
    ("nvapi", re.compile(r"nvapi-[A-Za-z0-9_\-]{20,}")),
    ("rtm_live", re.compile(r"rtm_[A-Za-z0-9_\-]{24,}")),
    ("pem", re.compile(r"-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----")),
    ("aws", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("gh_pat", re.compile(r"ghp_[A-Za-z0-9]{20,}")),
]

# Machine-local absolute paths that must not ship (patterns assembled so this
# file does not embed a real username or a contiguous machine temp path).
_HOME_ROOTS = ("Users", "home")
_SKIP_HOME_USERS = ("you", "YOU", "user", "username", "me", "someone")
HOME_PATH = re.compile(
    r"/(?:"
    + "|".join(_HOME_ROOTS)
    + r")/(?!(?:"
    + "|".join(_SKIP_HOME_USERS)
    + r"|<)[/\"'\s])[A-Za-z0-9._-]+"
)
# macOS agent/temp dirs: / + "var" + / + "folders" + /...
VAR_FOLDERS = re.compile(
    "/" + "var" + "/" + "folders" + r"/[A-Za-z0-9_./\-]+"
)
# harness scratch under system temp
TMP_ABS = re.compile(
    r"/(?:tmp|var/tmp)/[A-Za-z0-9_./\-]*"
    + "grok"
    + "-"
    + "goal"
    + r"[A-Za-z0-9_./\-]*"
)


def _is_placeholder(line: str) -> bool:
    low = line.lower()
    return any(
        x in low
        for x in (
            "example",
            "placeholder",
            "your_",
            "changeme",
            "xxxx",
            "fake",
            "test-not-a-real",
            "rtm_…",
            "rtm_...",
            "sk-test-placeholder",
            "<local-path>",
            "<repo-root>",
            "<you>",
        )
    )


def _line_at(text: str, pos: int) -> str:
    start = text.rfind("\n", 0, pos) + 1
    end = text.find("\n", pos)
    if end < 0:
        end = len(text)
    return text[start:end].strip()


def main() -> int:
    failed: list[str] = []
    scanned = 0
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [
            d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")
        ]
        if Path(dirpath).resolve() == ROOT.resolve() and ".github" in os.listdir(
            dirpath
        ):
            if ".github" not in dirnames:
                dirnames.append(".github")
        for fn in filenames:
            if fn in SKIP_NAMES or fn.startswith("ARCHITECTURE"):
                continue
            path = Path(dirpath) / fn
            rel = str(path.relative_to(ROOT))
            if path.suffix.lower() in {
                ".png",
                ".ico",
                ".jpg",
                ".jpeg",
                ".gif",
                ".svg",
                ".woff",
            }:
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            scanned += 1

            def hit(name: str, line: str) -> None:
                if _is_placeholder(line):
                    return
                if rel == ".env.example" and line.lstrip().startswith("#"):
                    return
                # Allow this test file's own pattern definitions (regex source)
                if rel.endswith("test_public_safety.py") and (
                    "re.compile" in line or "HOME_PATH" in line or "VAR_FOLDERS" in line
                ):
                    return
                failed.append(f"[{name}] {rel}: {line[:160]}")

            for name, pat in SECRET_PATTERNS:
                for m in pat.finditer(text):
                    hit(name, _line_at(text, m.start()))

            for m in HOME_PATH.finditer(text):
                hit("home_abs_path", _line_at(text, m.start()))

            for m in VAR_FOLDERS.finditer(text):
                hit("var_folders_path", _line_at(text, m.start()))

            for m in TMP_ABS.finditer(text):
                hit("tmp_harness_path", _line_at(text, m.start()))

    for need in (
        "LICENSE",
        "README.md",
        "Dockerfile",
        "docker-compose.yml",
        ".env.example",
        ".gitignore",
        "routism/server.py",
        "routism_cli/main.py",
        "ui/package.json",
        "tests/test_api_keys.py",
    ):
        if not (ROOT / need).is_file():
            failed.append(f"missing essential ship file: {need}")

    print(f"scanned={scanned}")
    if failed:
        print("FAIL public safety:")
        for f in failed:
            print(" ", f)
        return 1
    print("PASS public safety: no high-risk secrets/personal paths in ship surface")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
