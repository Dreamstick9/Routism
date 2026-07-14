"""Phase 6.E — Parallel orchestration engine driver.

Wires the full B (fan_out) → C (judge) → D (synthesize + verify) pipeline into
a single async call that emits the SSE event shapes ui/lib/api.ts expects.

HARD BOUNDARY (user, non-negotiable):
  * The engine brains used here are reserved models from orch.yaml ONLY.
  * This module imports routism_orch (engine_client, registry, judge, synthesize).
  * This module imports routism.worker ONLY for the user-facing fan_out —
    to call the user's opaque worker pool (black-box target). It NEVER treats
    a user worker as a brain.
  * The function emits the events ui/lib/api.ts dispatches:
      meta -> {mode, degraded, pool}
      fan_out -> {workers, roles}
      step -> {candidate: ParallelCandidate, ...} (one per worker as they arrive)
      scores -> [{worker_id, score, reason}]
      synthesis -> SynthesisTrace
      done -> {answer, usage, parallel: ParallelTrace, degraded, budget_hit}

Layered so SSE framing happens at the endpoint; this returns structured events.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import asdict
from typing import Any, AsyncIterator

from routism.config import OrchestratorNotConfigured  # noqa: F401  (used by endpoint glue)
from routism.worker import Worker, fan_out, fan_out_stream
from routism.config import Settings

from routism_orch import engine_client
from routism_orch.judge import (
    CandidateInput,
    CandidateScore,
    PairwiseResult,
    judge_all,
)
from routism_orch.registry import OrchRegistry, OrchModel
from routism_orch.synthesize import synthesize, verify_and_refine


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _candidate_input_from_fanout(results) -> list[CandidateInput]:
    """Map P6.B FanOutResult -> plain CandidateInput (engine-internal data)."""
    return [
        CandidateInput(
            worker_id=r.worker_id,
            role=r.role or "",
            answer=r.answer or "",
            error=r.error,
            elapsed_ms=r.elapsed_ms,
        )
        for r in results
    ]


def _sort_top(candidates: list[CandidateScore], k: int = 2) -> list[CandidateScore]:
    return sorted(candidates, key=lambda c: c.score, reverse=True)[:k]


# ---------------------------------------------------------------------------
# parallel orchestrate (real engine + workers)
# ---------------------------------------------------------------------------


async def parallel_orchestrate_stream(
    query: str,
    settings: Settings,
    *,
    registry: OrchRegistry | None = None,
    ollama_base_url: str = "http://localhost:11434",
    skip_meta: bool = False,
    degraded_reason: str | None = None,
    missing_engine_models: list[str] | None = None,
) -> AsyncIterator[dict]:
    """Stream the full P6 pipeline, yielding each SSE event dict AS IT HAPPENS.

    Yields events in order: meta -> fan_out -> step (per worker) -> scores ->
    synthesis -> done. The final `done` event carries the complete answer
    payload. The caller frames each yielded dict as an SSE `event:`/`data:`
    block; `parallel_orchestrate_events` drains this into a list for blocking
    callers.

    Engine availability is probed against the live Ollama server (not the
    always-present registry objects), so a server missing the reserved models
    degrades gracefully instead of erroring inside judge/synthesize.

    ``skip_meta``: when True, do NOT emit a meta event (Conductor engine-missing
    handoff already emitted exactly one degraded meta — avoid dual-meta).
    Optional ``degraded_reason`` / ``missing_engine_models`` are carried on
    ``done`` so the UI still sees them after a handoff.
    """
    reg = registry or OrchRegistry.load("routism_orch/orch.yaml")

    thinker = reg.coordinator()
    verifier = reg.verifier()
    judge2 = reg.judge2()

    pool: list[Worker] = list(settings.workers or [])
    started = time.time()

    # Real engine-up probe: are the reserved model tags actually pulled?
    # Registry objects are always present (hardcoded in orch.yaml) — only the
    # live Ollama /api/tags probe can detect a missing brain.
    loop = asyncio.get_event_loop()
    engine_ready, missing = await loop.run_in_executor(
        None,
        lambda: engine_client.engine_models_ready(reg, base_url=ollama_base_url),
    )
    engine_ok = bool(thinker and verifier and judge2 and engine_ready)
    # Caller-supplied missing list (e.g. Conductor handoff) wins for UX fields.
    miss_list = list(missing_engine_models) if missing_engine_models is not None else (
        list(missing) if not engine_ok else []
    )
    reason = degraded_reason
    if reason is None and not engine_ok:
        reason = "engine_unavailable"

    # ---- meta ---------------------------------------------------------
    if not skip_meta:
        yield {
            "_event": "meta",
            "mode": "complex",  # parallel = complex by definition
            "degraded": not engine_ok or bool(reason),
            "pool": [w.id for w in pool],
            "parallel": True,
            "missing_engine_models": miss_list,
            **({"degraded_reason": reason} if reason else {}),
        }

    # ---- handle empty pool --------------------------------------------
    if not pool:
        empty_ans = (
            "No workers are connected. Click 'Connect Ollama' (or add a Groq/Gemini "
            "worker) on the dashboard to power the orchestration engine."
        )
        parallel_trace: dict[str, Any] = {
            "fan_out": [],
            "synthesis": {"engine": "engine", "contributors": [], "draft": "", "strategy": "no-workers"},
            "final": empty_ans,
            "used_fallback": True,
        }
        yield {
            "_event": "done",
            "answer": empty_ans,
            "parallel": parallel_trace,
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            "degraded": True,
            "budget_hit": False,
        }
        return

    # ---- handle engine models unavailable -----------------------------
    # IMPORTANT: even without eng-thinker/verifier/judge2 we still fan out
    # to EVERY worker. The old single-worker fallback made Parallel look
    # completely broken when Ollama was cold/busy. Without the engine we
    # pick the longest non-empty answer as a crude "best" (no scoring).
    if not engine_ok:
        miss = ", ".join(missing) if missing else "unknown"
        yield {
            "_event": "fan_out",
            "workers": [w.id for w in pool],
            "roles": {w.id: "fallback" for w in pool},
        }
        results = []
        async for r in fan_out_stream(pool, [{"role": "user", "content": query}]):
            results.append(r)
            yield {
                "_event": "step",
                "candidate": {
                    "worker_id": r.worker_id,
                    "role": "fallback",
                    "answer": r.answer,
                    "score": 0.0,
                    "score_reason": f"engine offline (missing: {miss})",
                    "elapsed_ms": int(r.elapsed_ms or 0),
                    "error": r.error,
                },
            }
        ok = [r for r in results if r.ok and r.answer]
        best_id = None
        if ok:
            # crude pick: longest answer (no verifier available)
            best = max(ok, key=lambda r: len(r.answer or ""))
            best_id = best.worker_id
            ans = best.answer or ""
        else:
            errs = "; ".join(f"{r.worker_id}: {r.error or 'no answer'}" for r in results)
            ans = (
                f"Engine models unavailable on Ollama (missing: {miss}) and all "
                f"workers failed. Details: {errs}"
            )
        cand = []
        for r in results:
            is_best = best_id is not None and r.worker_id == best_id
            if is_best:
                score, reason = 5.0, f"fallback pick (engine offline: {miss})"
            elif r.error:
                score, reason = 0.0, f"worker failed: {r.error}"
            else:
                score, reason = 3.0, f"engine offline: {miss}"
            cand.append({
                "worker_id": r.worker_id,
                "role": "fallback",
                "answer": r.answer,
                "score": score,
                "score_reason": reason,
                "elapsed_ms": int(r.elapsed_ms or 0),
                "error": r.error,
            })
        yield {
            "_event": "scores",
            "data": [
                {"worker_id": c["worker_id"], "score": c["score"], "reason": c["score_reason"]}
                for c in cand
            ],
        }
        parallel_trace = {
            "fan_out": cand,
            "final": ans,
            "used_fallback": True,
            "engine_missing": list(missing) if missing else [],
        }
        done_payload = {
            "_event": "done",
            "answer": ans,
            "parallel": parallel_trace,
            "usage": {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "orchestration_input_tokens": 0,
                "orchestration_output_tokens": 0,
                "worker_prompt_tokens": 0,
                "worker_completion_tokens": 0,
            },
            "degraded": True,
            "budget_hit": False,
            "missing_engine_models": miss_list,
        }
        if reason:
            done_payload["degraded_reason"] = reason
        yield done_payload
        return

    # ---- fan_out event (announce workers + roles) --------------------
    yield {
        "_event": "fan_out",
        "workers": [w.id for w in pool],
        "roles": {w.id: "worker" for w in pool},
    }

    # ---- B: fan_out (real worker pool) --------------------------------
    # Stream results AS EACH worker finishes so the UI isn't frozen until
    # the slowest (or timed-out) worker returns. Failures stay isolated.
    results = []
    async for r in fan_out_stream(pool, [{"role": "user", "content": query}]):
        results.append(r)
        yield {
            "_event": "step",
            "candidate": {
                "worker_id": r.worker_id,
                "role": r.role or "worker",
                "answer": r.answer,
                "score": 0.0,          # filled in after judge
                "score_reason": "",
                "elapsed_ms": int(r.elapsed_ms or 0),
                "error": r.error,
            },
        }
    candidates_in = _candidate_input_from_fanout(results)

    # If every worker failed, surface a clear answer instead of empty synthesis.
    ok_results = [r for r in results if r.ok and r.answer]
    if not ok_results:
        errs = "; ".join(f"{r.worker_id}: {r.error or 'no answer'}" for r in results)
        empty_ans = (
            "All workers failed during fan-out. Check provider API keys, model "
            f"names, and base URLs. Details: {errs}"
        )
        parallel_trace = {
            "fan_out": [
                {
                    "worker_id": r.worker_id,
                    "role": r.role or "worker",
                    "answer": r.answer,
                    "score": 0.0,
                    "score_reason": "worker failed",
                    "elapsed_ms": int(r.elapsed_ms or 0),
                    "error": r.error,
                }
                for r in results
            ],
            "final": empty_ans,
            "used_fallback": True,
        }
        yield {
            "_event": "done",
            "answer": empty_ans,
            "parallel": parallel_trace,
            "usage": {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "orchestration_input_tokens": 0,
                "orchestration_output_tokens": 0,
                "worker_prompt_tokens": 0,
                "worker_completion_tokens": 0,
            },
            "degraded": True,
            "budget_hit": False,
        }
        return

    # ---- C: judge (engine-internal, runs verifier per candidate) -----
    scores, pairwise = await loop.run_in_executor(
        None,
        lambda: judge_all(reg, query, candidates_in),
    )

    # emit scores event — gate reads `.data`; UI accepts array OR {data: [...]}
    score_payload = [
        {"worker_id": s.worker_id, "score": s.score, "reason": s.reason}
        for s in scores
    ]
    yield {
        "_event": "scores",
        "data": score_payload,
    }

    # emit pairwise (optional) — one event even if winner=""
    if pairwise is not None:
        yield {
            "_event": "synthesis_prep",  # not part of UI contract — caller can ignore
            "_internal": "pairwise",
            "winner": pairwise.winner,
            "loser": pairwise.loser,
            "reason": pairwise.reason,
        }

    # build map of all candidate answers (for synthesize)
    answers = {r.worker_id: r.answer or "" for r in results if r.ok and r.answer}

    # ---- D: synthesize + verify (engine-internal) --------------------
    # Prefer scored successful workers; never let failed (score-0) candidates
    # crowd out real answers when choosing top-k.
    scored_ok = [s for s in scores if s.worker_id in answers]
    top = _sort_top(scored_ok or scores, k=2)

    def _synth_wrapper():
        return synthesize(thinker, query, top, answers, base_url=ollama_base_url)

    draft, synth_trace = await loop.run_in_executor(None, _synth_wrapper)

    def _verify_wrapper():
        return verify_and_refine(verifier, thinker, query, draft, base_url=ollama_base_url)

    final_text, verify_trace = await loop.run_in_executor(None, _verify_wrapper)

    # emit synthesis event (UI's onSynthesis handler reads the trace)
    yield {
        "_event": "synthesis",
        "engine": synth_trace.get("engine", thinker.id),
        "strategy": synth_trace.get("strategy", "merge-top-k"),
        "contributors": synth_trace.get("contributors", []),
        "draft": synth_trace.get("draft", draft),
    }

    # ---- done event ----------------------------------------------------
    score_by_id = {s.worker_id: s for s in scores}
    candidates_for_trace = []
    for r in results:
        s = score_by_id.get(r.worker_id)
        candidates_for_trace.append({
            "worker_id": r.worker_id,
            "role": r.role or "worker",
            "answer": r.answer,
            "score": float(s.score) if s else 0.0,
            "score_reason": s.reason if s else "",
            "elapsed_ms": int(r.elapsed_ms or 0),
            "error": r.error,
        })

    parallel_trace = {
        "fan_out": candidates_for_trace,
        "synthesis": synth_trace,
        "final": final_text,
        "used_fallback": verify_trace.get("accepted") is False,
    }
    if pairwise is not None:
        parallel_trace["pairwise"] = [
            {"winner": pairwise.winner, "loser": pairwise.loser, "reason": pairwise.reason}
        ]

    total_ms = int((time.time() - started) * 1000)
    yield {
        "_event": "done",
        "answer": final_text,
        "parallel": parallel_trace,
        "usage": {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": total_ms,
            # UI RunDoneEvent reads these keys for the token chips.
            "orchestration_input_tokens": 0,
            "orchestration_output_tokens": 0,
            "worker_prompt_tokens": 0,
            "worker_completion_tokens": 0,
        },
        "degraded": False,
        "budget_hit": False,
    }


async def parallel_orchestrate_events(
    query: str,
    settings: Settings,
    *,
    registry: OrchRegistry | None = None,
    ollama_base_url: str = "http://localhost:11434",
) -> tuple[dict, list[dict]]:
    """Blocking wrapper: drain the stream into (final_answer_dict, all_events).

    `final_answer_dict` is the `done` event payload (minus `_event`); the caller
    can build a JSON response from it. `all_events` is the ordered event list for
    callers that want the full trace without live streaming.
    """
    events: list[dict] = []
    final_answer_dict: dict = {}
    async for ev in parallel_orchestrate_stream(
        query, settings, registry=registry, ollama_base_url=ollama_base_url
    ):
        events.append(ev)
        if ev.get("_event") == "done":
            final_answer_dict = {k: v for k, v in ev.items() if k != "_event"}
    return final_answer_dict, events