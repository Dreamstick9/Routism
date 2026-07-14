"""Phase 7B — DAG Executor (Conductor Mode).

Extends the parallel orchestration pipeline to support Conductor Mode:
- Topological layer execution (fan_out per layer)
- Result propagation forward as context
- Per-layer scoring with eng-verifier
- Final synthesis with eng-thinker + verify gate
- PR-7: bounded replan when layer mean score < floor (≤1 replan)

Reuses existing parallel orchestration infrastructure (judge, synthesize, verify).
"""
from __future__ import annotations

import asyncio
import os
import time
import uuid
from typing import Any, AsyncIterator

from routism.config import Settings
from routism.worker import Worker, fan_out_varied

from routism_orch import engine_client
from routism_orch.registry import OrchRegistry
from routism_orch.judge import (
    CandidateInput,
    CandidateScore,
    pairwise,
    score_one,
)
from routism_orch.synthesize import (
    synthesize_with_pool,
    verify_and_refine,
    apply_merge_fallback_after_verify,
)
from routism_orch.conductor import (
    ConductorPlan,
    SampleResult,
    Subtask,
    reassign_subtask_workers,
)
from routism_orch.orchestrate_parallel import parallel_orchestrate_stream
from routism_orch.verify_node import check_success_criteria
from routism_orch.trajectory import log_trajectory, summarize_events


def _log_run_trajectory(
    *,
    run_id: str,
    query: str,
    plan: "ConductorPlan | None",
    events_acc: list[dict],
    done_ev: dict,
    scores: Any = None,
    models_used: list[str] | set[str] | None = None,
    win_vs_best: float | None = None,
) -> None:
    """Best-effort trajectory append at a done event. Never raises."""
    try:
        plan_dict = plan.to_dict() if plan is not None else {}
        models = models_used
        if models is None:
            cond = (done_ev.get("parallel") or {}).get("conductor") or {}
            models = cond.get("models_used") or []
        score_payload = scores
        if score_payload is None:
            fan = (done_ev.get("parallel") or {}).get("fan_out") or []
            score_payload = fan
        log_trajectory(
            run_id=run_id,
            query=query,
            plan_dict=plan_dict,
            events_summary=summarize_events(list(events_acc) + [done_ev]),
            final_answer=done_ev.get("answer"),
            scores=score_payload,
            models_used=models,
            win_vs_best=win_vs_best,
            degraded=bool(done_ev.get("degraded")),
            partial_success=bool(done_ev.get("partial_success")),
            degraded_reason=done_ev.get("degraded_reason"),
        )
    except Exception:
        pass


def _usage_dict(total_ms: int = 0) -> dict:
    """Usage shape both the gate and the UI token chips understand."""
    return {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": total_ms,
        "orchestration_input_tokens": 0,
        "orchestration_output_tokens": 0,
        "worker_prompt_tokens": 0,
        "worker_completion_tokens": 0,
    }


# ---------------------------------------------------------------------------
# PR-7 — Bounded replan (mean floor, ≤1 attempt)
# ---------------------------------------------------------------------------


def replan_enabled() -> bool:
    """CONDUCTOR_REPLAN default ON. Set 0/false/off to disable."""
    v = os.environ.get("CONDUCTOR_REPLAN", "1").strip().lower()
    return v not in ("0", "false", "no", "off")


def replan_floor() -> float:
    """Mean score floor below which remaining subgraph is replanned (default 4.0)."""
    try:
        return float(os.environ.get("CONDUCTOR_REPLAN_FLOOR", "4.0"))
    except (TypeError, ValueError):
        return 4.0


def successful_layer_scores(layer_subtasks: list[Subtask]) -> list[float]:
    """Scores of successful candidates (winner preferred) in a finished layer."""
    scores: list[float] = []
    for st in layer_subtasks:
        samples = list(st.samples or [])
        if st.result and not st.error:
            # Prefer the selected winner's score
            if st.selected_worker_id:
                for s in samples:
                    if (
                        s.worker_id == st.selected_worker_id
                        and s.score is not None
                        and s.answer
                        and not s.error
                    ):
                        scores.append(float(s.score))
                        break
                else:
                    ok = [
                        float(s.score)
                        for s in samples
                        if s.score is not None and s.answer and not s.error
                    ]
                    if ok:
                        scores.append(max(ok))
            else:
                ok = [
                    float(s.score)
                    for s in samples
                    if s.score is not None and s.answer and not s.error
                ]
                if ok:
                    scores.append(max(ok))
        else:
            # No winner, but still count any successful sample scores
            for s in samples:
                if s.answer and not s.error and s.score is not None:
                    scores.append(float(s.score))
    return scores


def layer_mean_score(layer_subtasks: list[Subtask]) -> float | None:
    """Mean of successful candidate scores; None if none succeeded."""
    scores = successful_layer_scores(layer_subtasks)
    if not scores:
        return None
    return sum(scores) / len(scores)


def should_replan(
    mean_score: float | None,
    replan_count: int,
    *,
    floor: float | None = None,
    enabled: bool | None = None,
) -> bool:
    """Pure decision: replan when mean < floor, budget left, and flag on.

    No successful candidates (mean is None) is treated as 0.0 — worse than floor.
    """
    if enabled is None:
        enabled = replan_enabled()
    if not enabled:
        return False
    if replan_count >= 1:
        return False
    fl = replan_floor() if floor is None else float(floor)
    m = 0.0 if mean_score is None else float(mean_score)
    return m < fl


def bounded_replan_remaining(
    plan: ConductorPlan,
    *,
    from_layer: int,
    layer_subtasks: list[Subtask],
    subtask_by_id: dict[str, Subtask],
    worker_tags: dict[str, list[str]],
    answers: dict[str, str],
    query: str,
    mean_score: float | None = None,
) -> list[str]:
    """Re-assign remaining incomplete subtasks and clear failed current-layer nodes.

    Targets:
      * failed nodes in the current layer (retry once)
      * all subtasks in layers after ``from_layer``

    Returns ordered list of subtask ids that were reset / reassigned.
    """
    from routism_orch.assign import (
        assign_k,
        assign_v2_enabled,
        get_worker_stats,
        k_sample_enabled,
    )

    remaining_ids: list[str] = []
    for st in layer_subtasks:
        if not st.result or st.error:
            remaining_ids.append(st.id)
    for layer in plan.layers[from_layer + 1 :]:
        for sid in layer:
            remaining_ids.append(sid)

    seen: set[str] = set()
    ordered: list[str] = []
    for sid in remaining_ids:
        if sid not in seen and sid in subtask_by_id:
            seen.add(sid)
            ordered.append(sid)

    if not ordered:
        return []

    # Usage from completed (kept) nodes so replan prefers different workers
    usage: dict[str, int] = {wid: 0 for wid in worker_tags}
    for st in plan.subtasks:
        if st.id in seen:
            continue
        picks = list(st.assigned_workers) if st.assigned_workers else []
        if not picks and st.assigned_worker:
            picks = [st.assigned_worker]
        for wid in picks:
            if wid in usage:
                usage[wid] = usage.get(wid, 0) + 1

    use_v2 = assign_v2_enabled()
    use_k = k_sample_enabled()
    stats = get_worker_stats() if use_v2 else None
    plan_size = max(1, len(plan.subtasks))
    mean_note = (
        f"{mean_score:.2f}" if mean_score is not None else "none (all failed)"
    )
    replan_suffix = (
        f"\n\n[Replan] Prior layer scored poorly (mean={mean_note}). "
        f"Original request: {query[:240]}. Prefer a clearer, more correct approach."
    )

    for sid in ordered:
        st = subtask_by_id[sid]
        # Drop any prior answers keyed under this subtask
        for key in list(answers.keys()):
            # cand ids: worker/subtask or worker/subtask/sN
            parts = key.split("/")
            if len(parts) >= 2 and parts[1] == sid:
                del answers[key]

        prev = list(st.assigned_workers) if st.assigned_workers else []
        if not prev and st.assigned_worker:
            prev = [st.assigned_worker]
        # Bias away from previous assignees so retry gets different workers
        for wid in prev:
            if wid in usage:
                usage[wid] = usage.get(wid, 0) + 2

        st.result = None
        st.error = None
        st.samples = []
        st.selected_worker_id = None
        st.elapsed_ms = None
        if hasattr(st, "_k_method"):
            try:
                delattr(st, "_k_method")
            except Exception:
                pass

        k = 2 if (use_k and st.critical) else 1
        picks, reason = assign_k(
            st.tags,
            worker_tags,
            k=k,
            stats=stats,
            usage=usage,
            assign_v2=use_v2,
            plan_size=plan_size,
        )
        st.assigned_workers = list(picks)
        st.assigned_worker = picks[0] if picks else None
        st.assignment_reason = f"replan:{reason}"

        if "[Replan]" not in (st.prompt or ""):
            st.prompt = (st.prompt or "") + replan_suffix

    return ordered


def _cand_id(st: Subtask) -> str:
    """Stable unique id for a subtask result (survives same-worker reuse)."""
    worker = st.selected_worker_id or st.assigned_worker or "unassigned"
    return f"{worker}/{st.id}"


def _sample_cand_id(worker_id: str, subtask_id: str, sample_index: int) -> str:
    """Unique id for a k-sample attempt (UI + scoring)."""
    return f"{worker_id}/{subtask_id}/s{sample_index}"


def _dep_context(st: Subtask, subtask_by_id: dict[str, Subtask]) -> str:
    if not st.depends_on:
        return ""
    dep_results = []
    for dep_id in st.depends_on:
        dep_st = subtask_by_id.get(dep_id)
        if dep_st and dep_st.result:
            dep_results.append(f"--- Output from {dep_id} ---\n{dep_st.result}")
    return "\n\n".join(dep_results) + "\n\n" if dep_results else ""


def _select_k_sample_winner(
    st: Subtask,
    samples: list[SampleResult],
    *,
    subtask_question: str,
    registry: OrchRegistry,
    ollama_base_url: str,
) -> tuple[SampleResult | None, str]:
    """Pick winner among scored samples. Pairwise only for same-prompt ties.

    Returns (winner_or_None, method).
    """
    ok = [s for s in samples if s.answer and not s.error]
    if not ok:
        return None, "all_failed"
    if len(ok) == 1:
        return ok[0], "sole_survivor"

    ok_sorted = sorted(ok, key=lambda s: (s.score is not None, s.score or 0.0), reverse=True)
    a, b = ok_sorted[0], ok_sorted[1]
    sa = a.score if a.score is not None else 0.0
    sb = b.score if b.score is not None else 0.0
    if abs(sa - sb) <= 1.0:
        j2 = registry.judge2()
        j2_ready = False
        if j2 is not None:
            ready, _ = engine_client.engine_models_ready(
                registry, base_url=ollama_base_url, roles=["judge2"]
            )
            j2_ready = ready
        if j2 is not None and j2_ready:
            ca = CandidateInput(
                worker_id=a.worker_id,
                answer=a.answer,
                role=f"conductor:{st.id}",
                elapsed_ms=float(a.elapsed_ms or 0),
            )
            cb = CandidateInput(
                worker_id=b.worker_id,
                answer=b.answer,
                role=f"conductor:{st.id}",
                elapsed_ms=float(b.elapsed_ms or 0),
            )
            pw = pairwise(j2, subtask_question, ca, cb, base_url=ollama_base_url)
            if pw.winner == a.worker_id:
                return a, "pairwise"
            if pw.winner == b.worker_id:
                return b, "pairwise"
            return a, "absolute_fallback"
    return a, "absolute"


# ---------------------------------------------------------------------------
# Conductor DAG Executor
# ---------------------------------------------------------------------------


async def execute_conductor_stream(
    query: str,
    settings: Settings,
    plan: "ConductorPlan",
    registry: OrchRegistry,
    ollama_base_url: str = "http://localhost:11434",
) -> AsyncIterator[dict]:
    """Execute a Conductor plan DAG layer by layer, streaming events live.

    Yields SSE event dicts as each stage completes: meta -> conductor_plan ->
    (per layer) dag_layer_start / step / scores / dag_layer_complete ->
    synthesis -> done. The `done` event carries the full answer payload.

    Fixes over earlier versions:
      * Each subtask gets its OWN prompt via `fan_out_varied`.
      * Engine availability is probed against the live Ollama server.
      * Subtasks the planner left unassigned fall back to the least-used pool
        worker instead of being silently dropped.
      * Candidate ids are unique per subtask (`worker/subtask`) so two DAG
        nodes routed to the same worker never clobber each other in the UI
        or synthesizer answer map.
      * meta.mode is "complex" (UI contract); conductor-ness is signaled via
        dag_layers / conductor_plan events.
    """
    pool: list[Worker] = list(settings.workers or [])
    started = time.time()
    loop = asyncio.get_event_loop()
    run_id = uuid.uuid4().hex
    events_acc: list[dict] = []

    # Probe BEFORE meta so we never flash healthy then fail (PR-1 contract).
    # Conductor k=1 needs thinker+verifier only; judge2 is optional (score_only).
    thinker = registry.coordinator()
    verifier = registry.verifier()
    engine_ready, missing = await loop.run_in_executor(
        None,
        lambda: engine_client.engine_models_ready(
            registry,
            base_url=ollama_base_url,
            roles=["coordinator", "verifier"],
        ),
    )
    engine_ok = bool(thinker and verifier and engine_ready)

    # ---- handle empty pool --------------------------------------------
    if not pool:
        meta_ev = {
            "_event": "meta",
            "mode": "complex",
            "degraded": True,
            "pool": [],
            "parallel": True,
            "dag_layers": len(plan.layers),
            "dag_subtasks": len(plan.subtasks),
            "orchestration": "conductor",
            "degraded_reason": "no_workers",
            "missing_engine_models": [],
        }
        events_acc.append(meta_ev)
        yield meta_ev
        no_workers = "No workers connected."
        done_ev = {
            "_event": "done",
            "answer": no_workers,
            "parallel": {
                "fan_out": [],
                "synthesis": {},
                "final": no_workers,
                "used_fallback": True,
            },
            "usage": _usage_dict(),
            "degraded": True,
            "degraded_reason": "no_workers",
            "missing_engine_models": [],
            "budget_hit": False,
            "run_id": run_id,
        }
        _log_run_trajectory(
            run_id=run_id,
            query=query,
            plan=plan,
            events_acc=events_acc,
            done_ev=done_ev,
            scores=[],
            models_used=[],
        )
        yield done_ev
        return

    # ---- engine missing: exactly ONE degraded meta, then Parallel handoff ----
    # Never silent pool[0]-only. skip_meta avoids a second meta from Parallel.
    if not engine_ok:
        miss = list(missing) if missing else []
        if not thinker:
            miss = list(dict.fromkeys(miss + ["coordinator"]))
        if not verifier:
            miss = list(dict.fromkeys(miss + ["verifier"]))
        reason = "engine_unavailable"
        meta_ev = {
            "_event": "meta",
            "mode": "complex",
            "degraded": True,
            "pool": [w.id for w in pool],
            "parallel": True,
            "dag_layers": len(plan.layers),
            "dag_subtasks": len(plan.subtasks),
            "orchestration": "conductor_degraded",
            "degraded_reason": reason,
            "missing_engine_models": miss,
        }
        events_acc.append(meta_ev)
        yield meta_ev
        async for ev in parallel_orchestrate_stream(
            query,
            settings,
            registry=registry,
            ollama_base_url=ollama_base_url,
            skip_meta=True,
            degraded_reason=reason,
            missing_engine_models=miss,
        ):
            events_acc.append(ev)
            if ev.get("_event") == "done":
                done_ev = dict(ev)
                done_ev.setdefault("run_id", run_id)
                _log_run_trajectory(
                    run_id=run_id,
                    query=query,
                    plan=plan,
                    events_acc=events_acc[:-1],
                    done_ev=done_ev,
                    models_used=[w.id for w in pool],
                )
                yield done_ev
            else:
                yield ev
        return

    # ---- healthy Conductor meta (single meta for this run) -------------
    meta_ev = {
        "_event": "meta",
        "mode": "complex",  # UI chip contract: trivial | complex
        "degraded": False,
        "pool": [w.id for w in pool],
        "parallel": True,
        "dag_layers": len(plan.layers),
        "dag_subtasks": len(plan.subtasks),
        "orchestration": "conductor",
        "missing_engine_models": [],
        "run_id": run_id,
    }
    events_acc.append(meta_ev)
    yield meta_ev

    # ---- Conductor Plan event -----------------------------------------
    # Include full connected pool so the UI roster never undercounts when the
    # plan assigns a subset (or when meta was missed / stale).
    plan_ev = {
        "_event": "conductor_plan",
        "query": query,
        "layers": len(plan.layers),
        "subtasks": len(plan.subtasks),
        "pool": [w.id for w in pool],
        "plan": plan.to_dict(),
    }
    events_acc.append(plan_ev)
    yield plan_ev

    # Fan-out announcement so the UI lights the parallel badge immediately.
    fan_ev = {
        "_event": "fan_out",
        "workers": [w.id for w in pool],
        "roles": {
            (st.assigned_worker or pool[0].id): f"conductor:{st.id}"
            for st in plan.subtasks
        },
    }
    events_acc.append(fan_ev)
    yield fan_ev

    worker_by_id = {w.id: w for w in pool}
    subtask_by_id = {s.id: s for s in plan.subtasks}
    worker_tags = {w.id: list(w.tags or []) for w in pool}
    all_scores: list[CandidateScore] = []
    # Map unique cand id -> answer text for the synthesizer (winners only)
    answers: dict[str, str] = {}
    partial_success = False
    replan_count = 0

    # Guard: never no-op on non-empty plan (empty/broken layers → one flat layer)
    if plan.subtasks:
        if not plan.layers or all(not (layer or []) for layer in plan.layers):
            plan.layers = [[s.id for s in plan.subtasks]]
        else:
            # Drop empty slots; if nothing left, flatten
            plan.layers = [list(L) for L in plan.layers if L]
            if not plan.layers:
                plan.layers = [[s.id for s in plan.subtasks]]
            else:
                # Ensure every subtask appears in some layer
                seen = {sid for L in plan.layers for sid in L}
                missing = [s.id for s in plan.subtasks if s.id not in seen]
                if missing:
                    plan.layers.append(missing)

    # ---- Execute DAG layer by layer -----------------------------------
    for layer_idx, layer_ids in enumerate(plan.layers):
        layer_start = time.time()

        yield {
            "_event": "dag_layer_start",
            "layer": layer_idx,
            "subtask_ids": layer_ids,
        }

        # Expand jobs: one per (subtask, sample). k-sample critical nodes may
        # fan to 2 distinct workers with the same subtask prompt.
        layer_subtasks = [subtask_by_id[sid] for sid in layer_ids if sid in subtask_by_id]
        jobs: list[tuple[Worker, list[dict]]] = []
        # job_meta aligned with jobs: (subtask, sample_index, worker_id, prompt_text)
        job_meta: list[tuple[Subtask, int, str, str]] = []
        for i, st in enumerate(layer_subtasks):
            picks = list(st.assigned_workers) if st.assigned_workers else []
            if not picks and st.assigned_worker:
                picks = [st.assigned_worker]
            if not picks:
                picks = [pool[i % len(pool)].id]
            # Drop unknown ids; fall back to pool round-robin
            resolved: list[str] = []
            for wid in picks:
                if wid in worker_by_id:
                    resolved.append(wid)
            if not resolved:
                resolved = [pool[i % len(pool)].id]
            st.assigned_workers = resolved
            st.assigned_worker = resolved[0]

            context = _dep_context(st, subtask_by_id)
            prompt = f"{context}{st.prompt}"
            for si, wid in enumerate(resolved):
                jobs.append((worker_by_id[wid], [{"role": "user", "content": prompt}]))
                job_meta.append((st, si, wid, prompt))

        # ---- Fan out this layer (per-sample prompts) -----------------
        layer_results = await fan_out_varied(jobs, timeout=120.0)

        # Group samples by subtask id (preserve order of first appearance)
        samples_by_st: dict[str, list[SampleResult]] = {st.id: [] for st in layer_subtasks}
        prompt_by_st: dict[str, str] = {}
        for (st, si, wid, prompt), res in zip(job_meta, layer_results):
            prompt_by_st[st.id] = prompt
            samples_by_st[st.id].append(
                SampleResult(
                    worker_id=wid,
                    answer=res.answer,
                    error=res.error,
                    elapsed_ms=res.elapsed_ms,
                    sample_index=si,
                )
            )
            # step event per sample (unique id for UI)
            yield {
                "_event": "step",
                "candidate": {
                    "worker_id": _sample_cand_id(wid, st.id, si),
                    "role": f"conductor:{st.id}",
                    "answer": res.answer,
                    "score": 0.0,
                    "score_reason": "",
                    "elapsed_ms": int(res.elapsed_ms or 0),
                    "error": res.error,
                },
            }

        # ---- Score samples per-subtask (absolute, subtask-local question) -
        layer_score_rows: list[dict] = []
        verifier = registry.verifier()

        def _score_layer() -> None:
            from routism_orch.assign import get_worker_stats

            stats = get_worker_stats()
            for st in layer_subtasks:
                samples = samples_by_st.get(st.id, [])
                st.samples = samples
                # Score against THIS node's work order + success_criteria only
                sub_q = st.prompt or f"Subtask {st.id}"
                if verifier is not None:
                    for s in samples:
                        cs = score_one(
                            verifier,
                            sub_q,
                            CandidateInput(
                                worker_id=_sample_cand_id(s.worker_id, st.id, s.sample_index),
                                answer=s.answer,
                                role=f"conductor:{st.id}",
                                error=s.error,
                                elapsed_ms=float(s.elapsed_ms or 0),
                            ),
                            base_url=ollama_base_url,
                            success_criteria=getattr(st, "success_criteria", "") or "",
                            overall_goal=query,
                        )
                        s.score = cs.score
                        s.score_reason = cs.reason
                        layer_score_rows.append(
                            {
                                "worker_id": cs.worker_id,
                                "score": cs.score,
                                "reason": cs.reason,
                            }
                        )
                        all_scores.append(cs)
                        if s.answer and not s.error:
                            stats.record_outcome(
                                s.worker_id,
                                score_0_10=float(cs.score),
                                latency_ms=float(s.elapsed_ms)
                                if s.elapsed_ms is not None
                                else None,
                            )
                # Select winner (pairwise only on same-prompt k-sample ties)
                winner, method = _select_k_sample_winner(
                    st,
                    samples,
                    subtask_question=sub_q,
                    registry=registry,
                    ollama_base_url=ollama_base_url,
                )
                if winner is None:
                    st.result = None
                    # Prefer concrete sample error over generic message
                    errs = [s.error for s in samples if s.error]
                    st.error = (errs[0] if errs else "all samples failed")
                    st.selected_worker_id = None
                    nonlocal_partial[0] = True
                    st._needs_reassign = bool(st.critical)  # type: ignore[attr-defined]
                else:
                    st.result = winner.answer or ""
                    st.error = winner.error
                    st.elapsed_ms = winner.elapsed_ms
                    st.selected_worker_id = winner.worker_id
                    st.assigned_worker = winner.worker_id
                    if st.result:
                        answers[_cand_id(st)] = st.result
                    # Winner score also under stable cand id for synth top-k
                    if winner.score is not None:
                        all_scores.append(
                            CandidateScore(
                                worker_id=_cand_id(st),
                                role=f"conductor:{st.id}",
                                score=float(winner.score),
                                reason=winner.score_reason or method,
                                elapsed_ms=float(winner.elapsed_ms or 0),
                            )
                        )
                # Stash method on a private attribute for event emit after executor
                st._k_method = method  # type: ignore[attr-defined]

        # nonlocal flag via list cell (executor closure)
        nonlocal_partial = [partial_success]
        await loop.run_in_executor(None, _score_layer)
        if nonlocal_partial[0]:
            partial_success = True

        # ---- Critical fail: reassign once to different workers ----------
        reassign_jobs: list[tuple[Worker, list[dict]]] = []
        reassign_meta: list[tuple[Subtask, int, str, str]] = []
        for st in layer_subtasks:
            if not getattr(st, "_needs_reassign", False):
                continue
            if st.result:
                continue
            failed_ids = {
                s.worker_id
                for s in (st.samples or [])
                if s.worker_id and (s.error or not s.answer)
            }
            if st.assigned_worker:
                failed_ids.add(st.assigned_worker)
            new_picks = reassign_subtask_workers(
                plan,
                st.id,
                worker_tags,
                exclude_ids=failed_ids,
                health=None,
                k=1,
            )
            if not new_picks:
                continue
            # skip if same as already failed
            if set(new_picks) <= failed_ids:
                continue
            for si, wid in enumerate(new_picks):
                if wid not in worker_by_id:
                    continue
                context = _dep_context(st, subtask_by_id)
                prompt = f"{context}{st.prompt}"
                reassign_jobs.append(
                    (worker_by_id[wid], [{"role": "user", "content": prompt}])
                )
                reassign_meta.append((st, si, wid, prompt))
            st._needs_reassign = False  # type: ignore[attr-defined]

        if reassign_jobs:
            ra_results = await fan_out_varied(reassign_jobs, timeout=120.0)

            def _score_reassign() -> None:
                for (st, si, wid, _p), res in zip(reassign_meta, ra_results):
                    sample = SampleResult(
                        worker_id=wid,
                        answer=res.answer,
                        error=res.error,
                        elapsed_ms=res.elapsed_ms,
                        sample_index=len(st.samples or []),
                    )
                    st.samples = list(st.samples or []) + [sample]
                    if res.error or not res.answer:
                        st.error = res.error or st.error or "reassign failed"
                        continue
                    sample.score = None
                    if verifier is not None:
                        cs = score_one(
                            verifier,
                            st.prompt or "",
                            CandidateInput(
                                worker_id=_sample_cand_id(wid, st.id, sample.sample_index),
                                answer=sample.answer,
                                role=f"conductor:{st.id}",
                                error=sample.error,
                                elapsed_ms=float(sample.elapsed_ms or 0),
                            ),
                            base_url=ollama_base_url,
                            success_criteria=getattr(st, "success_criteria", "") or "",
                            overall_goal=query,
                        )
                        sample.score = cs.score
                        sample.score_reason = cs.reason
                        all_scores.append(cs)
                    st.result = sample.answer or ""
                    st.error = None
                    st.elapsed_ms = sample.elapsed_ms
                    st.selected_worker_id = wid
                    st.assigned_worker = wid
                    if st.result:
                        answers[_cand_id(st)] = st.result
                    if sample.score is not None:
                        all_scores.append(
                            CandidateScore(
                                worker_id=_cand_id(st),
                                role=f"conductor:{st.id}",
                                score=float(sample.score),
                                reason=sample.score_reason or "reassign",
                                elapsed_ms=float(sample.elapsed_ms or 0),
                            )
                        )

            await loop.run_in_executor(None, _score_reassign)

        # ---- Success criteria: one retry then score penalty ----------
        # Nodes whose result fails keyword/all-of criteria re-run the same
        # worker once; if still failing, lower the winner score for synth.
        retry_jobs: list[tuple[Worker, list[dict]]] = []
        retry_meta: list[tuple[Subtask, str, str]] = []
        for st in layer_subtasks:
            if not st.result:
                continue
            ok, reason = check_success_criteria(
                st.result, getattr(st, "success_criteria", "") or ""
            )
            st._criteria_ok = ok  # type: ignore[attr-defined]
            st._criteria_reason = reason  # type: ignore[attr-defined]
            if ok:
                continue
            wid = st.selected_worker_id or st.assigned_worker
            if not wid or wid not in worker_by_id:
                continue
            if getattr(st, "_criteria_retried", False):
                continue
            context = _dep_context(st, subtask_by_id)
            prompt = f"{context}{st.prompt}"
            retry_jobs.append(
                (worker_by_id[wid], [{"role": "user", "content": prompt}])
            )
            retry_meta.append((st, wid, prompt))
            st._criteria_retried = True  # type: ignore[attr-defined]

        if retry_jobs:
            retry_results = await fan_out_varied(retry_jobs, timeout=120.0)
            retry_score_rows: list[dict] = []

            def _score_retries() -> None:
                for (st, wid, _prompt), res in zip(retry_meta, retry_results):
                    # Append retry as an extra sample (index = len(samples))
                    si = len(st.samples or [])
                    sample = SampleResult(
                        worker_id=wid,
                        answer=res.answer,
                        error=res.error,
                        elapsed_ms=res.elapsed_ms,
                        sample_index=si,
                    )
                    st.samples = list(st.samples or []) + [sample]
                    sub_q = st.prompt or f"Subtask {st.id}"
                    if verifier is not None and sample.answer and not sample.error:
                        cs = score_one(
                            verifier,
                            sub_q,
                            CandidateInput(
                                worker_id=_sample_cand_id(wid, st.id, si),
                                answer=sample.answer,
                                role=f"conductor:{st.id}",
                                error=sample.error,
                                elapsed_ms=float(sample.elapsed_ms or 0),
                            ),
                            base_url=ollama_base_url,
                            success_criteria=getattr(st, "success_criteria", "") or "",
                            overall_goal=query,
                        )
                        sample.score = cs.score
                        sample.score_reason = cs.reason
                        retry_score_rows.append(
                            {
                                "worker_id": cs.worker_id,
                                "score": cs.score,
                                "reason": cs.reason,
                            }
                        )
                        all_scores.append(cs)

                    # Prefer retry answer if it has content
                    if sample.answer and not sample.error:
                        st.result = sample.answer
                        st.error = sample.error
                        st.elapsed_ms = sample.elapsed_ms
                        st.selected_worker_id = wid
                        st.assigned_worker = wid
                        answers[_cand_id(st)] = st.result
                        # Re-check criteria on the retry result
                        ok2, reason2 = check_success_criteria(
                            st.result, getattr(st, "success_criteria", "") or ""
                        )
                        st._criteria_ok = ok2  # type: ignore[attr-defined]
                        st._criteria_reason = reason2  # type: ignore[attr-defined]
                        # Update winner score entry under stable cand id
                        if sample.score is not None:
                            # Drop prior winner entry for this cand id, re-add
                            for i in range(len(all_scores) - 1, -1, -1):
                                if all_scores[i].worker_id == _cand_id(st):
                                    all_scores.pop(i)
                                    break
                            final_score = float(sample.score)
                            reason_txt = sample.score_reason or "criteria_retry"
                            if not ok2:
                                final_score = max(0.0, final_score * 0.5)
                                reason_txt = (
                                    f"criteria_fail({reason2}); lowered"
                                )
                            all_scores.append(
                                CandidateScore(
                                    worker_id=_cand_id(st),
                                    role=f"conductor:{st.id}",
                                    score=final_score,
                                    reason=reason_txt,
                                    elapsed_ms=float(sample.elapsed_ms or 0),
                                )
                            )
                    else:
                        # Retry failed; keep original result, lower its score
                        st._criteria_ok = False  # type: ignore[attr-defined]
                        for i, cs in enumerate(all_scores):
                            if cs.worker_id == _cand_id(st):
                                lowered = max(0.0, float(cs.score) * 0.5)
                                all_scores[i] = CandidateScore(
                                    worker_id=cs.worker_id,
                                    role=cs.role,
                                    score=lowered,
                                    reason=(
                                        f"criteria_fail("
                                        f"{getattr(st, '_criteria_reason', '')}); "
                                        f"retry_failed; lowered"
                                    ),
                                    elapsed_ms=cs.elapsed_ms,
                                )
                                break

            await loop.run_in_executor(None, _score_retries)
            if retry_score_rows:
                layer_score_rows.extend(retry_score_rows)

        # Nodes that failed criteria but were not retried (or still fail
        # after path above without score update) — apply score penalty.
        for st in layer_subtasks:
            if not st.result:
                continue
            ok = getattr(st, "_criteria_ok", None)
            if ok is None:
                ok, reason = check_success_criteria(
                    st.result, getattr(st, "success_criteria", "") or ""
                )
                st._criteria_ok = ok  # type: ignore[attr-defined]
                st._criteria_reason = reason  # type: ignore[attr-defined]
            if ok:
                continue
            # Already penalized on retry path if _criteria_retried and score updated
            if getattr(st, "_criteria_penalized", False):
                continue
            cid = _cand_id(st)
            for i, cs in enumerate(all_scores):
                if cs.worker_id == cid:
                    if "criteria_fail" in (cs.reason or ""):
                        break  # already lowered
                    lowered = max(0.0, float(cs.score) * 0.5)
                    all_scores[i] = CandidateScore(
                        worker_id=cs.worker_id,
                        role=cs.role,
                        score=lowered,
                        reason=(
                            f"criteria_fail("
                            f"{getattr(st, '_criteria_reason', '')}); lowered"
                        ),
                        elapsed_ms=cs.elapsed_ms,
                    )
                    st._criteria_penalized = True  # type: ignore[attr-defined]
                    break

        if layer_score_rows:
            yield {
                "_event": "scores",
                "data": layer_score_rows,
            }

        # k_sample_pick events for nodes that actually had k>1 samples
        for st in layer_subtasks:
            samples = st.samples or []
            if len(samples) < 2:
                continue
            method = getattr(st, "_k_method", "absolute")
            winner_id = st.selected_worker_id
            losers = [s.worker_id for s in samples if s.worker_id != winner_id]
            yield {
                "_event": "k_sample_pick",
                "subtask_id": st.id,
                "winner": winner_id,
                "losers": losers,
                "method": method,
                "scores": [
                    {
                        "worker_id": s.worker_id,
                        "score": s.score,
                        "sample_index": s.sample_index,
                    }
                    for s in samples
                ],
            }

        # ---- PR-7: mean score of successful candidates + bounded replan -
        mean = layer_mean_score(layer_subtasks)
        mean_for_event: float = 0.0 if mean is None else float(mean)

        if should_replan(mean, replan_count):
            replan_ids = bounded_replan_remaining(
                plan,
                from_layer=layer_idx,
                layer_subtasks=layer_subtasks,
                subtask_by_id=subtask_by_id,
                worker_tags=worker_tags,
                answers=answers,
                query=query,
                mean_score=mean,
            )
            replan_count = 1
            reason = (
                f"layer_{layer_idx}_mean_"
                f"{'none' if mean is None else f'{mean:.2f}'}"
                f"_below_{replan_floor():.1f}"
            )
            yield {
                "_event": "replan",
                "layer": layer_idx,
                "mean_score": mean_for_event,
                "reason": reason,
                "new_subtask_ids": replan_ids,
            }

            # Retry failed/cleared nodes of *this* layer once with new workers.
            # Future layers keep reassigned workers for their normal turn.
            retry_sts = [st for st in layer_subtasks if st.id in set(replan_ids)]
            if retry_sts:
                retry_jobs: list[tuple[Worker, list[dict]]] = []
                retry_job_meta: list[tuple[Subtask, int, str, str]] = []
                for i, st in enumerate(retry_sts):
                    picks = list(st.assigned_workers) if st.assigned_workers else []
                    if not picks and st.assigned_worker:
                        picks = [st.assigned_worker]
                    if not picks:
                        picks = [pool[i % len(pool)].id]
                    resolved: list[str] = [
                        wid for wid in picks if wid in worker_by_id
                    ]
                    if not resolved:
                        resolved = [pool[i % len(pool)].id]
                    st.assigned_workers = resolved
                    st.assigned_worker = resolved[0]
                    context = _dep_context(st, subtask_by_id)
                    prompt = f"{context}{st.prompt}"
                    for si, wid in enumerate(resolved):
                        retry_jobs.append(
                            (
                                worker_by_id[wid],
                                [{"role": "user", "content": prompt}],
                            )
                        )
                        retry_job_meta.append((st, si, wid, prompt))

                replan_results = await fan_out_varied(retry_jobs, timeout=120.0)
                samples_by_st_rp: dict[str, list[SampleResult]] = {
                    st.id: [] for st in retry_sts
                }
                for (st, si, wid, _prompt), res in zip(
                    retry_job_meta, replan_results
                ):
                    samples_by_st_rp[st.id].append(
                        SampleResult(
                            worker_id=wid,
                            answer=res.answer,
                            error=res.error,
                            elapsed_ms=res.elapsed_ms,
                            sample_index=si,
                        )
                    )
                    yield {
                        "_event": "step",
                        "candidate": {
                            "worker_id": _sample_cand_id(wid, st.id, si),
                            "role": f"conductor:{st.id}",
                            "answer": res.answer,
                            "score": 0.0,
                            "score_reason": "replan_retry",
                            "elapsed_ms": int(res.elapsed_ms or 0),
                            "error": res.error,
                        },
                    }

                replan_score_rows: list[dict] = []
                verifier_rp = registry.verifier()

                def _score_replan_retry() -> None:
                    from routism_orch.assign import get_worker_stats

                    stats = get_worker_stats()
                    for st in retry_sts:
                        samples = samples_by_st_rp.get(st.id, [])
                        st.samples = samples
                        sub_q = (
                            f"Original user request: {query}\n"
                            f"This subtask's goal ({st.id}): {st.prompt}"
                        )
                        if verifier_rp is not None:
                            for s in samples:
                                cs = score_one(
                                    verifier_rp,
                                    sub_q,
                                    CandidateInput(
                                        worker_id=_sample_cand_id(
                                            s.worker_id, st.id, s.sample_index
                                        ),
                                        answer=s.answer,
                                        role=f"conductor:{st.id}",
                                        error=s.error,
                                        elapsed_ms=float(s.elapsed_ms or 0),
                                    ),
                                    base_url=ollama_base_url,
                                )
                                s.score = cs.score
                                s.score_reason = cs.reason
                                replan_score_rows.append(
                                    {
                                        "worker_id": cs.worker_id,
                                        "score": cs.score,
                                        "reason": cs.reason or "replan_retry",
                                    }
                                )
                                all_scores.append(cs)
                                if s.answer and not s.error:
                                    stats.record_outcome(
                                        s.worker_id,
                                        score_0_10=float(cs.score),
                                        latency_ms=float(s.elapsed_ms)
                                        if s.elapsed_ms is not None
                                        else None,
                                    )
                        winner, method = _select_k_sample_winner(
                            st,
                            samples,
                            subtask_question=sub_q,
                            registry=registry,
                            ollama_base_url=ollama_base_url,
                        )
                        if winner is None:
                            st.result = None
                            st.error = "all samples failed"
                            st.selected_worker_id = None
                            nonlocal_partial_rp[0] = True
                        else:
                            st.result = winner.answer or ""
                            st.error = winner.error
                            st.elapsed_ms = winner.elapsed_ms
                            st.selected_worker_id = winner.worker_id
                            st.assigned_worker = winner.worker_id
                            if st.result:
                                answers[_cand_id(st)] = st.result
                            if winner.score is not None:
                                all_scores.append(
                                    CandidateScore(
                                        worker_id=_cand_id(st),
                                        role=f"conductor:{st.id}",
                                        score=float(winner.score),
                                        reason=winner.score_reason
                                        or method
                                        or "replan_retry",
                                        elapsed_ms=float(
                                            winner.elapsed_ms or 0
                                        ),
                                    )
                                )
                        st._k_method = method  # type: ignore[attr-defined]

                nonlocal_partial_rp = [partial_success]
                await loop.run_in_executor(None, _score_replan_retry)
                if nonlocal_partial_rp[0]:
                    partial_success = True

                if replan_score_rows:
                    yield {"_event": "scores", "data": replan_score_rows}

                for st in retry_sts:
                    samples = st.samples or []
                    if len(samples) < 2:
                        continue
                    method = getattr(st, "_k_method", "absolute")
                    winner_id = st.selected_worker_id
                    losers = [
                        s.worker_id
                        for s in samples
                        if s.worker_id != winner_id
                    ]
                    yield {
                        "_event": "k_sample_pick",
                        "subtask_id": st.id,
                        "winner": winner_id,
                        "losers": losers,
                        "method": method,
                        "scores": [
                            {
                                "worker_id": s.worker_id,
                                "score": s.score,
                                "sample_index": s.sample_index,
                            }
                            for s in samples
                        ],
                    }

                mean = layer_mean_score(layer_subtasks)
                mean_for_event = 0.0 if mean is None else float(mean)

        layer_ms = int((time.time() - layer_start) * 1000)
        yield {
            "_event": "dag_layer_complete",
            "layer": layer_idx,
            "elapsed_ms": layer_ms,
            "subtask_count": len(layer_subtasks),
            "mean_score": mean_for_event,
            "replan_count": replan_count,
        }

    # ---- Synthesize final answer (pool-merge or eng-thinker) ----------
    scores = list(all_scores)
    # Prefer successful subtask outputs with the highest scores.
    scored_ok = [s for s in scores if s.worker_id in answers]
    top = sorted(scored_ok or scores, key=lambda c: c.score, reverse=True)[: max(2, len(plan.subtasks))]
    # Cap top-k for the synthesizer prompt size.
    top = top[:4]

    # If nothing scored (all workers failed), surface a clear error.
    if not answers:
        errs = "; ".join(
            f"{st.id}@{st.assigned_worker}: {st.error or 'no answer'}"
            for st in plan.subtasks
        )
        empty_ans = f"Conductor DAG produced no successful subtask outputs. {errs}"
        done_ev = {
            "_event": "done",
            "answer": empty_ans,
            "parallel": {
                "fan_out": [
                    {
                        "worker_id": _cand_id(st),
                        "role": f"conductor:{st.id}",
                        "answer": st.result or "",
                        "score": 0.0,
                        "score_reason": "failed",
                        "elapsed_ms": int(st.elapsed_ms or 0),
                        "error": st.error,
                    }
                    for st in plan.subtasks
                ],
                "final": empty_ans,
                "used_fallback": True,
            },
            "usage": _usage_dict(int((time.time() - started) * 1000)),
            "degraded": True,
            "partial_success": True,
            "budget_hit": False,
            "run_id": run_id,
        }
        _log_run_trajectory(
            run_id=run_id,
            query=query,
            plan=plan,
            events_acc=events_acc,
            done_ev=done_ev,
            scores=scores,
            models_used=[],
        )
        yield done_ev
        return

    # Mark partial if any node failed while others succeeded
    if any(not st.result for st in plan.subtasks):
        partial_success = True

    # ---- Final recovery: fill holes before stitch (product path) ----
    from routism_orch.recovery_fill import recovery_fill_failed_nodes

    prefer_code = [
        w.id
        for w in pool
        if any(t in (w.tags or []) for t in ("code", "reasoning"))
    ] or [w.id for w in pool]

    async def _call_worker_for_recovery(
        wid: str, prompt: str
    ) -> tuple[str | None, str | None, float]:
        ww = worker_by_id.get(wid)
        if ww is None:
            return None, f"unknown worker {wid}", 0.0
        try:
            results = await fan_out_varied(
                [(ww, [{"role": "user", "content": prompt}])],
                timeout=120.0,
            )
            res = results[0] if results else None
            if res is None:
                return None, "no recovery result", 0.0
            return res.answer, res.error, float(res.elapsed_ms or 0)
        except Exception as e:  # noqa: BLE001
            return None, f"{type(e).__name__}: {e}", 0.0

    rec_out = await recovery_fill_failed_nodes(
        query=query,
        subtasks=list(plan.subtasks),
        pool_ids=[w.id for w in pool],
        call_worker=_call_worker_for_recovery,
        prefer_code_ids=prefer_code,
    )
    for rr in rec_out:
        if rr.recovered and rr.answer:
            st = subtask_by_id.get(rr.subtask_id)
            if st is not None:
                answers[_cand_id(st)] = st.result or rr.answer
            all_scores.append(
                CandidateScore(
                    worker_id=f"{rr.worker_id}/{rr.subtask_id}",
                    role=f"conductor:{rr.subtask_id}",
                    score=7.0,
                    reason="recovery_fill",
                    elapsed_ms=float(rr.elapsed_ms or 0),
                )
            )
            yield {
                "_event": "step",
                "candidate": {
                    "worker_id": f"{rr.worker_id}/{rr.subtask_id}",
                    "role": f"conductor:{rr.subtask_id}:recovery",
                    "answer": rr.answer,
                    "score": 7.0,
                    "score_reason": "recovery_fill",
                    "elapsed_ms": int(rr.elapsed_ms or 0),
                    "error": None,
                },
            }
    partial_success = any(
        not (st.result and not st.error) for st in plan.subtasks
    )

    def _synth_wrapper():
        # ENGINE-ONLY sectioned merge (workers never synthesize).
        step_rows = []
        for st in plan.subtasks:
            # Short title from first line of work order assignment if possible
            title = st.id
            p = (st.prompt or "")
            for line in p.splitlines():
                if line.strip() and not line.startswith("#") and "goal" not in line.lower()[:20]:
                    title = line.strip()[:80]
                    break
            score_v = None
            for cs in all_scores:
                if cs.worker_id == _cand_id(st) or (
                    st.selected_worker_id and st.selected_worker_id in (cs.worker_id or "")
                ):
                    score_v = cs.score
                    break
            step_rows.append(
                {
                    "id": st.id,
                    "title": title,
                    "result": st.result,
                    "error": st.error,
                    "score": score_v,
                    "worker_id": st.selected_worker_id or st.assigned_worker,
                }
            )
        return synthesize_with_pool(
            query,
            top if top else [
                CandidateScore(
                    worker_id=_cand_id(st),
                    role=f"conductor:{st.id}",
                    score=5.0,
                    reason="unscored",
                )
                for st in plan.subtasks
                if st.result
            ],
            answers,
            registry,
            workers=None,  # never pool-merge on product path
            ollama_base_url=ollama_base_url,
            step_rows=step_rows,
        )

    draft, synth_trace = await loop.run_in_executor(None, _synth_wrapper)
    # Preserve pool-merge / merge-top-k / best_sample_fallback; default label for UI.
    if isinstance(synth_trace, dict):
        synth_trace = {**synth_trace, "strategy": synth_trace.get("strategy") or "conductor-merge"}

    def _verify_wrapper():
        return verify_and_refine(
            registry.verifier(),
            registry.coordinator(),
            query,
            draft,
            base_url=ollama_base_url,
        )

    final_text, verify_trace = await loop.run_in_executor(None, _verify_wrapper)

    # T1.5: if verify rejects (or merge was weak), prefer best high-scoring sample
    cand_for_fb = top if top else [
        CandidateScore(
            worker_id=_cand_id(st),
            role=f"conductor:{st.id}",
            score=5.0,
            reason="unscored",
        )
        for st in plan.subtasks
        if st.result
    ]
    final_text, verify_trace = apply_merge_fallback_after_verify(
        final_text, verify_trace, cand_for_fb, answers
    )
    if verify_trace.get("used_best_sample_fallback") and isinstance(synth_trace, dict):
        synth_trace = {
            **synth_trace,
            "strategy": "best_sample_fallback",
            "engine": verify_trace.get("best_sample_id") or synth_trace.get("engine"),
            "used_best_sample_fallback": True,
        }

    synth_ev = {
        "_event": "synthesis",
        "engine": synth_trace.get("engine", "eng-thinker"),
        "strategy": synth_trace.get("strategy", "conductor-merge"),
        "contributors": synth_trace.get("contributors", []),
        "draft": synth_trace.get("draft", draft),
    }
    events_acc.append(synth_ev)
    yield synth_ev

    # ---- Build final parallel trace -----------------------------------
    score_by_id = {s.worker_id: s for s in scores}
    candidates_for_trace = []
    models_used: set[str] = set()
    for st in plan.subtasks:
        cid = _cand_id(st)
        s = score_by_id.get(cid)
        candidates_for_trace.append({
            "worker_id": cid,
            "role": f"conductor:{st.id}",
            "answer": st.result or "",
            "score": float(s.score) if s else 0.0,
            "score_reason": s.reason if s else "",
            "elapsed_ms": int(st.elapsed_ms or 0),
            "error": st.error,
        })
        if st.selected_worker_id:
            models_used.add(st.selected_worker_id)
        elif st.assigned_worker and st.result:
            models_used.add(st.assigned_worker)

    parallel_trace = {
        "fan_out": candidates_for_trace,
        "synthesis": synth_trace,
        "final": final_text,
        "used_fallback": bool(
            verify_trace.get("accepted") is False
            or verify_trace.get("used_best_sample_fallback")
            or synth_trace.get("used_best_sample_fallback")
        ),
        "conductor": {
            "layers": plan.layers,
            "subtasks": [st.to_dict() for st in plan.subtasks],
            "models_used": sorted(models_used),
            "models_used_count": len(models_used),
            "pool_size": len(pool),
        },
    }
    total_ms = int((time.time() - started) * 1000)
    # Optional win_vs_best: final vs best single-sample score (0-10 scale → ratio-ish)
    win_vs_best: float | None = None
    try:
        if scores:
            best_s = max(float(s.score) for s in scores if s.score is not None)
            # Heuristic: mean of top scores as quality proxy when no external judge
            win_vs_best = round(best_s / 10.0, 4) if best_s is not None else None
    except Exception:
        win_vs_best = None
    done_ev = {
        "_event": "done",
        "answer": final_text,
        "parallel": parallel_trace,
        "usage": _usage_dict(total_ms),
        "degraded": False,
        "partial_success": partial_success,
        "budget_hit": False,
        "run_id": run_id,
        "models_used": sorted(models_used),
    }
    _log_run_trajectory(
        run_id=run_id,
        query=query,
        plan=plan,
        events_acc=events_acc,
        done_ev=done_ev,
        scores=scores,
        models_used=models_used,
        win_vs_best=win_vs_best,
    )
    yield done_ev


async def execute_conductor_dag(
    query: str,
    settings: Settings,
    plan: "ConductorPlan",
    registry: OrchRegistry,
    ollama_base_url: str = "http://localhost:11434",
) -> tuple[dict, list[dict]]:
    """Blocking wrapper: drain `execute_conductor_stream` into (final, events)."""
    events: list[dict] = []
    final_answer_dict: dict = {}
    async for ev in execute_conductor_stream(
        query, settings, plan, registry, ollama_base_url=ollama_base_url
    ):
        events.append(ev)
        if ev.get("_event") == "done":
            final_answer_dict = {k: v for k, v in ev.items() if k != "_event"}
    return final_answer_dict, events


# ---------------------------------------------------------------------------
# Compatibility wrapper for parallel_orchestrate_events (unchanged Parallel Mode)
# ---------------------------------------------------------------------------

# The existing parallel_orchestrate_events is preserved in orchestrate_parallel.py
# This module adds execute_conductor_dag / execute_conductor_stream for Conductor Mode.
