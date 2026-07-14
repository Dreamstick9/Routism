"""Public boundary: `orchestrate(query, pool, settings, *, fallback)`.

Importable by `routism/server.py`. The app passes its ≤5 user models as `pool`
and supplies `safe_plan` as the fallback for when the head is untrained.
"""
from __future__ import annotations

from typing import Any, Callable

from .engine import OrchestrateResult, OrchestrationEngine


def orchestrate(
    query: str,
    pool: list[str],
    settings: Any,
    *,
    fallback: Callable[[str, Any], tuple[Any, bool]] | None = None,
) -> OrchestrateResult:
    engine = OrchestrationEngine()
    return engine.orchestrate(query, pool, settings, fallback=fallback)
