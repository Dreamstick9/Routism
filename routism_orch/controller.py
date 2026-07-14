"""Path controller — Conductor-only product surface.

Routism exposes one orchestration mode: Conductor (team DAG). Parallel vote
and auto→fast/vote paths are retired. ``classify_difficulty`` remains for
telemetry / eval; ``resolve_path`` always returns ``team``.
"""
from __future__ import annotations

import os
import re
from typing import Literal

PathKind = Literal["fast", "team", "vote"]

_SEQUENCE_RE = re.compile(
    r"\b(?:and then|then|after that|afterward|afterwards|followed by|"
    r"next|finally|also|step by step|first .+ then)\b",
    re.I,
)
_MULTI_SKILL_RE = re.compile(
    r"\b(implement|function|code|pytest|test|design|api|explain|summarize|"
    r"review|debug|prove|calculate)\b",
    re.I,
)


def controller_enabled() -> bool:
    v = os.environ.get("CONDUCTOR_CONTROLLER", "1").strip().lower()
    return v not in ("0", "false", "no", "off")


def classify_difficulty(query: str) -> PathKind:
    """Heuristic difficulty label (telemetry). Product path is always team."""
    q = (query or "").strip()
    if not q:
        return "fast"
    words = len(q.split())
    has_seq = bool(_SEQUENCE_RE.search(q))
    skills = len(set(m.group(0).lower() for m in _MULTI_SKILL_RE.finditer(q)))
    if has_seq or words > 50 or skills >= 2:
        return "team"
    if words > 30 and skills >= 1:
        return "team"
    return "fast"


def resolve_path(
    query: str,
    mode: str | None,
) -> PathKind:
    """Always Conductor (team). ``mode`` / query ignored for path selection.

    Accepts legacy mode strings (``parallel``, ``auto``) for API compatibility
    but never routes to vote/fast — those surfaces are removed.
    """
    _ = query
    _ = mode
    return "team"
