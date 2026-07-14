"""Phase 2B — Zero-Router baseline system.

The counterfactual RouterBench compares against: send the WHOLE query to one
best worker, no orchestration, no decomposition. Exposes the same
`System.run(query) -> RunResult` interface the Benchmark harness expects, so it
drops in unchanged.

Token accounting uses the same `_est_tokens` heuristic as the executor — fine for
*relative* comparison (Routism vs Zero-Router on the same queries). Real systems
return their measured tokens; this baseline estimates locally.
"""

from __future__ import annotations

from .config import Settings, Worker, OrchestratorNotConfigured
from .eval import RunResult, System
from .worker import complete as worker_complete
from . import worker as worker_mod
from . import orchestrator as orch_mod
from . import executor as executor_mod
from . import classifier as classifier_mod
from .schema import Step, Workflow
from contextlib import contextmanager
from typing import Iterator


def _est_tokens(text: str) -> int:
    """Rough token estimate (~4 chars/token), matching executor accounting."""
    return max(1, len(text) // 4)


@contextmanager
def _patch_complete(fn) -> Iterator[None]:
    """Temporarily swap worker.complete for an injected fn (offline testing)."""
    real = worker_mod.complete
    worker_mod.complete = fn
    try:
        yield
    finally:
        worker_mod.complete = real


class ZeroRouter:
    """Baseline: whole query -> single best worker. No orchestration."""

    def __init__(
        self,
        settings: Settings,
        pick: str = "first",
        complete_fn=None,
    ):
        """
        pick: "first" -> pool[0]; (future: "cheapest"/"fastest" hooks).
        complete_fn: injectable for tests (defaults to the real worker.complete).
        """
        if not settings.workers:
            raise ValueError("ZeroRouter needs at least one worker in the pool")
        self.settings = settings
        self.pick = pick
        self._complete = complete_fn or worker_complete
        self._worker = self._select(settings.workers)

    def _select(self, workers: list[Worker]) -> Worker:
        if self.pick == "first":
            return workers[0]
        # extensible later; default to first
        return workers[0]

    def run(self, query: str) -> RunResult:
        answer = self._complete(
            self._worker, [{"role": "user", "content": query}], retries=1
        )
        return RunResult(
            answer=answer,
            input_tokens=_est_tokens(query),
            output_tokens=_est_tokens(answer),
        )


class RoutismSystem:
    """The real Routism pipeline as a `System`: orchestrator plan -> executor.

    Mirrors the server's `_build_workflow` + `executor.run_detailed` path so the
    eval exercises the same code the API serves. `complete_fn` is injected (and
    swapped over `worker.complete` for the duration of `run`) so the gate runs
    fully offline without a model/network.
    """

    def __init__(self, settings: Settings, complete_fn=None):
        self.settings = settings
        self._complete_fn = complete_fn

    def _build_workflow(self, query: str) -> tuple[str, Workflow]:
        if not self.settings.workers:
            raise OrchestratorNotConfigured("no workers configured in pool")
        mode = classifier_mod.classify(query)
        if mode == "trivial":
            # Mirror server.py:59-64 exactly. A trivial query routes through the
            # DEDICATED orchestrator (settings.orchestrator), which raises
            # OrchestratorNotConfigured when orchestrator_worker_id is unset.
            # This makes eval match prod: a config prod would 500 on, eval now
            # reports ok=False rather than green on trivial queries.
            best = self.settings.orchestrator
            wf = Workflow(steps=[Step(subtask=query, worker_id=best.id, access_list=[])])
        else:
            wf = orch_mod.plan(query, self.settings)
        return mode, wf

    def run(self, query: str) -> RunResult:
        if self._complete_fn is not None:
            with _patch_complete(self._complete_fn):
                return self._run_inner(query)
        return self._run_inner(query)

    def _run_inner(self, query: str) -> RunResult:
        _, workflow = self._build_workflow(query)
        trace = executor_mod.run_detailed(workflow, self.settings)
        return RunResult(
            answer=trace["answer"],
            input_tokens=trace["orchestration_input_tokens"],
            output_tokens=trace["orchestration_output_tokens"],
        )
