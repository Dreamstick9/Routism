"""Node-level success criteria checks for Conductor DAG subtasks.

Lightweight keyword/all-of gate used after a subtask produces a result.
Does not call an LLM — criteria tokens must appear in the result text.
"""
from __future__ import annotations

import re


def check_success_criteria(result: str, criteria: str) -> tuple[bool, str]:
    """Return (passed, reason) for keyword/all-of success criteria.

    Rules:
      - Empty / whitespace-only criteria → pass ("no criteria").
      - Split criteria on ``;`` or the word ``AND`` (case-insensitive).
      - Every non-empty token must appear in ``result`` (case-insensitive).
    """
    if criteria is None or not str(criteria).strip():
        return True, "no criteria"

    parts = re.split(r"\s*;\s*|\s+AND\s+", str(criteria).strip(), flags=re.IGNORECASE)
    tokens = [p.strip() for p in parts if p and p.strip()]
    if not tokens:
        return True, "no criteria"

    haystack = (result or "").lower()
    missing = [t for t in tokens if t.lower() not in haystack]
    if missing:
        return False, "missing: " + ", ".join(missing)
    return True, "all criteria met"
