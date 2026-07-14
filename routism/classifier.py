"""P0.E — complexity classifier (two-mode routing).

Decides whether a query is handled by a fast 1-step short-circuit (trivial) or
the full multi-step orchestrator workflow (complex). This is a deterministic
heuristic so it is cheap, predictable, and needs no LLM call. A real product
could swap this for a small classifier model, but the contract stays the same.
"""
from __future__ import annotations

import re

# Signals that a query needs multi-step decomposition.
_COMPLEX_PATTERNS = [
    r"\bthen\b",                 # "do X then Y"
    r"\band\b",                  # "compare X and Y"
    r"\bbut\b",
    r"\bcompare\b",
    r"\bdesign\b",
    r"\bbuild\b",
    r"\bwrite\b",                # "write tests for it"
    r"\bplan\b",
    r"\bstep[s-]?by-step\b",
    r"\bversus\b|\bvs\.?\b",
    r"\bexplain\b.*\bwhy\b",
    r"\bfirst\b.*\bsecond\b",
    r"\bcreate\b",
    r"\bimplement\b",
    r"\blist\b.*\bsteps\b",
]

_COMPLEX_RE = re.compile("|".join(_COMPLEX_PATTERNS), re.IGNORECASE)

# Starters that almost always mean a short factual answer -> trivial even if a
# weak complex word appears (e.g. "What is 2+2 and 2?" should not decompose).
_TRIVIAL_STARTERS = (
    "what is", "what's", "who is", "who's", "name a", "name the",
    "define", "how many", "when is", "where is",
)

# A "trivial" query is short and factual (e.g. "What is 2+2?", "Name a planet").
_TRIVIAL_MAX_WORDS = 6
_TRIVIAL_STARTER_MAX_WORDS = 10


def classify(query: str) -> str:
    """Return 'trivial' or 'complex' (see `route` for the rationale)."""
    return route(query)["mode"]


def route(query: str) -> dict:
    """Return {'mode': 'trivial'|'complex', 'reason': str}.

    Heuristic, deterministic (no LLM call):
    - empty -> trivial
    - short factual starter (what is / who is / ...) with <= 10 words -> trivial
    - <= 6 words and no complex pattern -> trivial
    - otherwise -> complex
    The contract is conservative: when in doubt we decompose (over-trigger is
    safe; under-trigger would skip needed orchestration).
    """
    q = (query or "").strip()
    if not q:
        return {"mode": "trivial", "reason": "empty query"}
    words = q.split()
    low = q.lower()
    if low.startswith(_TRIVIAL_STARTERS) and len(words) <= _TRIVIAL_STARTER_MAX_WORDS:
        return {"mode": "trivial", "reason": f"factual starter, {len(words)} words"}
    if len(words) <= _TRIVIAL_MAX_WORDS and not _COMPLEX_RE.search(q):
        return {"mode": "trivial", "reason": f"short ({len(words)}w), no complex signal"}
    return {
        "mode": "complex",
        "reason": "long or carries a decompose signal"
        + (" (pattern)" if _COMPLEX_RE.search(q) else f" ({len(words)}w)"),
    }
