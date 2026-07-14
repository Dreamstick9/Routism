"""Parse engine model tags from routism_orch/orch.yaml."""

from __future__ import annotations

import re
from pathlib import Path
from typing import List

from .util import ok, warn

DEFAULT_ENGINE_TAGS = [
    "qwen2.5:7b",
    "deepseek-r1:1.5b",
]


def _parse_with_yaml(text: str) -> List[str]:
    import yaml  # type: ignore

    data = yaml.safe_load(text) or {}
    models = data.get("models") or []
    tags: List[str] = []
    seen = set()
    for m in models:
        if not isinstance(m, dict):
            continue
        tag = m.get("model")
        if tag and tag not in seen:
            seen.add(tag)
            tags.append(str(tag))
    return tags


def _parse_with_regex(text: str) -> List[str]:
    """
    Lightweight fallback: collect `model: xxx` lines that appear under the
    top-level `models:` list (before the next top-level key like capability_registry).
    """
    # Slice to models: section only (indent 0 key)
    m = re.search(r"(?m)^models:\s*\n", text)
    if not m:
        return []
    start = m.end()
    rest = text[start:]
    end_m = re.search(r"(?m)^[a-zA-Z_][a-zA-Z0-9_]*:\s*", rest)
    section = rest[: end_m.start()] if end_m else rest

    tags: List[str] = []
    seen = set()
    for match in re.finditer(
        r"(?m)^\s+model:\s*([^\s#]+)",
        section,
    ):
        tag = match.group(1).strip().strip("\"'")
        if tag and tag not in seen:
            seen.add(tag)
            tags.append(tag)
    return tags


def load_engine_tags(repo_root: Path) -> List[str]:
    path = repo_root / "routism_orch" / "orch.yaml"
    if not path.is_file():
        warn(f"orch.yaml not found at {path}; using defaults")
        return list(DEFAULT_ENGINE_TAGS)

    text = path.read_text(encoding="utf-8")
    tags: List[str] = []
    try:
        tags = _parse_with_yaml(text)
    except Exception:
        tags = []

    if not tags:
        tags = _parse_with_regex(text)

    if not tags:
        warn("Could not parse engine models from orch.yaml; using defaults")
        return list(DEFAULT_ENGINE_TAGS)

    ok(f"Engine models from orch.yaml: {', '.join(tags)}")
    return tags


def unique_tags(tags: List[str]) -> List[str]:
    out: List[str] = []
    seen = set()
    for t in tags:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out
