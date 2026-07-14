"""Orchestration engine facade.

The real engine lives in :mod:`routism.engine` (a dedicated, stateful Conductor
with its own toolset and embedded turn state). This module keeps the historical
``plan(query, settings)`` entry point so the server/executor keep working.
"""
from __future__ import annotations

from .config import Settings
from .engine import OrchestrationEngine
from . import worker as worker_mod
from .schema import Workflow


def plan(query: str, settings: Settings, *, retries: int = 3) -> Workflow:
    """Decompose ``query`` into a Workflow via the dedicated orchestration engine.

    If the engine cannot run (e.g. no dedicated orchestrator configured), surface
    it as a :class:`WorkerError` so the API layer returns a friendly message
    instead of a 500.
    """
    from .config import OrchestratorNotConfigured

    try:
        return OrchestrationEngine(settings).plan(query, retries=retries)
    except OrchestratorNotConfigured as e:
        raise worker_mod.WorkerError(str(e)) from e


def safe_plan(query: str, settings: Settings, *, retries: int = 3) -> tuple[Workflow, bool]:
    """Best-effort planning: degrade to a single direct step if the Conductor
    (a possibly-weak local model) cannot produce a valid + audited plan.

    Returns ``(workflow, used_fallback)``. ``used_fallback`` is True when the
    query was routed to one direct worker instead of a multi-step plan. This is
    what stops a tiny orchestrator from failing an entire request (the live eval
    saw trivial queries fail outright when the 1b conductor emitted broken JSON).
    """
    from .config import OrchestratorNotConfigured

    try:
        return OrchestrationEngine(settings).safe_plan(query, retries=retries)
    except OrchestratorNotConfigured as e:
        # Conductor not configured at all — cannot even build a fallback plan.
        raise worker_mod.WorkerError(str(e)) from e


def revise(
    query: str,
    prior: Workflow,
    rejections: list[tuple[int, str]],
    settings: Settings,
    *,
    retries: int = 3,
    engine: "OrchestrationEngine | None" = None,
) -> Workflow:
    """Multi-turn REFLECT: revise ``prior`` using verifier ``rejections``.

    Surfaces engine-not-configured as a :class:`WorkerError`. Pass an existing
    ``engine`` (e.g. one with an injected Brain) to reuse its state/tools.
    """
    from .config import OrchestratorNotConfigured

    try:
        eng = engine if engine is not None else OrchestrationEngine(settings)
        return eng.revise(query, prior, rejections, retries=retries)
    except OrchestratorNotConfigured as e:
        raise worker_mod.WorkerError(str(e)) from e
