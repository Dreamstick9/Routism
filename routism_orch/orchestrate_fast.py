"""Self-MoA fast path — sample the single best worker k times (Princeton Self-MoA).

Research: multi-sample from the best model often beats mixed MoA on easy tasks.
When the difficulty controller classifies a query as ``fast``, this path:

  1. Picks the best healthy worker by tags (general/chat/code from query keywords)
     plus latency EMA when WorkerStats has samples.
  2. Calls that same worker k times (``CONDUCTOR_SELF_MOA_K``, default 2) with
     slight temperature diversity (or identical prompt if k==1).
  3. Scores samples with eng-verifier ``score_one`` when the engine is ready;
     else picks the longest non-empty answer.
  4. Streams SSE events compatible with ui/lib/api.ts:
       meta → fan_out → step (per sample) → scores → done

Flag: ``CONDUCTOR_FAST_PATH=1`` (default on). Set 0 to force legacy full parallel
for auto/easy queries.
"""
from __future__ import annotations

import asyncio
import os
import re
import time
from typing import Any, AsyncIterator

import httpx

from routism.config import Settings
from routism.worker import Worker, FanOutResult, _a_complete_full

from routism_orch import engine_client
from routism_orch.assign import (
    get_worker_stats,
    rank_workers,
    snapshot_worker_health,
)
from routism_orch.judge import CandidateInput, score_one
from routism_orch.registry import OrchRegistry


# ---------------------------------------------------------------------------
# Flags
# ---------------------------------------------------------------------------


def fast_path_enabled() -> bool:
    """CONDUCTOR_FAST_PATH default ON: Self-MoA on best worker for easy queries."""
    v = os.environ.get("CONDUCTOR_FAST_PATH", "1").strip().lower()
    return v not in ("0", "false", "no", "off")


def self_moa_k() -> int:
    """How many samples of the best worker (default 2, clamped 1..5)."""
    try:
        return max(1, min(5, int(os.environ.get("CONDUCTOR_SELF_MOA_K", "2"))))
    except ValueError:
        return 2


# ---------------------------------------------------------------------------
# Query → soft tags (general / chat / code)
# ---------------------------------------------------------------------------

_CODE_RE = re.compile(
    r"\b(code|function|implement|debug|python|pytest|typescript|javascript|"
    r"api|refactor|compile|syntax|bug|unit\s*test|snippet|class|def)\b",
    re.I,
)
_CHAT_RE = re.compile(
    r"\b(hi|hello|hey|thanks|thank you|how are you|good morning|good evening|"
    r"what's up|whats up|yo)\b",
    re.I,
)


def infer_query_tags(query: str) -> list[str]:
    """Map easy-query keywords → capability tags for best-worker ranking.

    Returns one of: ``[\"code\"]``, ``[\"chat\"]``, or ``[\"general\"]``.
    """
    q = (query or "").strip()
    if not q:
        return ["general"]
    if _CODE_RE.search(q):
        return ["code"]
    words = q.split()
    if len(words) <= 6 and _CHAT_RE.search(q):
        return ["chat"]
    if len(words) <= 4 and not _CODE_RE.search(q):
        return ["chat"]
    return ["general"]


# ---------------------------------------------------------------------------
# Best worker selection
# ---------------------------------------------------------------------------


def pick_best_worker(
    workers: list[Worker],
    query: str,
    *,
    health: dict[str, bool] | None = None,
) -> tuple[Worker | None, str]:
    """Pick best worker: health + inferred tags + rank (latency via stats).

    Returns (worker_or_None, reason).
    """
    if not workers:
        return None, "empty_pool"

    tags_wanted = infer_query_tags(query)
    worker_tags = {w.id: list(w.tags or []) for w in workers}
    by_id = {w.id: w for w in workers}

    if health is None:
        try:
            health = snapshot_worker_health(list(workers))
        except Exception:
            health = {w.id: True for w in workers}

    stats = get_worker_stats()
    ranked, scores, degraded = rank_workers(
        tags_wanted,
        worker_tags,
        health=health,
        stats=stats,
        usage={w.id: 0 for w in workers},
    )
    if not ranked:
        # last resort: first worker
        w = workers[0]
        return w, "fallback_first"

    top_id = ranked[0]
    reason_bits = [
        f"self_moa tags={tags_wanted}",
        f"score={scores.get(top_id, 0.0):.3f}",
    ]
    st = stats.get(top_id)
    if st.latency_ema is not None:
        reason_bits.append(f"lat_ema={st.latency_ema:.0f}ms")
    if degraded:
        reason_bits.append(degraded)
    return by_id[top_id], "; ".join(reason_bits)


# ---------------------------------------------------------------------------
# Sample temperatures (slight diversity for Self-MoA)
# ---------------------------------------------------------------------------

# k samples get mild temperature spread; index 0 is cooler / more deterministic.
_TEMPS = (0.2, 0.55, 0.75, 0.9, 1.0)


def _sample_temp(index: int) -> float:
    return float(_TEMPS[min(index, len(_TEMPS) - 1)])


def _sample_id(worker_id: str, sample_index: int) -> str:
    return f"{worker_id}/s{sample_index}"


# ---------------------------------------------------------------------------
# Stream
# ---------------------------------------------------------------------------


async def self_moa_fast_stream(
    query: str,
    settings: Settings,
    *,
    registry: OrchRegistry | None = None,
    ollama_base_url: str = "http://localhost:11434",
    k: int | None = None,
) -> AsyncIterator[dict]:
    """Self-MoA on best worker: yield SSE event dicts (``_event`` keyed).

    Event order: meta → fan_out → step×k → scores → done.
    """
    reg = registry or OrchRegistry.load("routism_orch/orch.yaml")
    pool: list[Worker] = list(settings.workers or [])
    started = time.time()
    k = self_moa_k() if k is None else max(1, min(5, int(k)))

    loop = asyncio.get_event_loop()
    engine_ready, missing = await loop.run_in_executor(
        None,
        lambda: engine_client.engine_models_ready(
            reg, base_url=ollama_base_url, roles=["verifier"]
        ),
    )
    verifier = reg.verifier()
    engine_ok = bool(verifier and engine_ready)
    miss_list = list(missing) if not engine_ok else []

    # ---- empty pool -------------------------------------------------------
    if not pool:
        empty = (
            "No workers are connected. Click 'Connect Ollama' (or add a "
            "Groq/Gemini worker) on the dashboard to power the orchestration engine."
        )
        yield {
            "_event": "meta",
            "mode": "trivial",
            "degraded": True,
            "pool": [],
            "parallel": False,
            "self_moa": True,
            "orchestration": "self_moa",
            "path": "fast",
            "degraded_reason": "no_workers",
        }
        yield {
            "_event": "done",
            "answer": empty,
            "parallel": {
                "fan_out": [],
                "final": empty,
                "used_fallback": True,
                "strategy": "self_moa",
            },
            "usage": _usage(0),
            "degraded": True,
            "budget_hit": False,
            "degraded_reason": "no_workers",
        }
        return

    # ---- pick best worker -------------------------------------------------
    health = await loop.run_in_executor(
        None, lambda: snapshot_worker_health(list(pool))
    )
    best, pick_reason = pick_best_worker(pool, query, health=health)
    assert best is not None

    yield {
        "_event": "meta",
        "mode": "trivial",
        "degraded": not engine_ok,
        "pool": [best.id],
        "parallel": False,
        "self_moa": True,
        "orchestration": "self_moa",
        "path": "fast",
        "self_moa_k": k,
        "best_worker": best.id,
        "assignment_reason": pick_reason,
        "missing_engine_models": miss_list,
        **({"degraded_reason": "engine_unavailable"} if not engine_ok else {}),
    }

    sample_ids = [_sample_id(best.id, i) for i in range(k)]
    yield {
        "_event": "fan_out",
        "workers": sample_ids,
        "roles": {sid: f"self_moa:s{i}" for i, sid in enumerate(sample_ids)},
    }

    # ---- k samples of the same worker -------------------------------------
    messages = [{"role": "user", "content": query}]
    results: list[tuple[int, FanOutResult]] = []

    async def _one(si: int) -> tuple[int, FanOutResult]:
        t0 = time.monotonic()
        temp = _sample_temp(si)
        try:
            async with httpx.AsyncClient(timeout=best.timeout_s or 60.0) as client:
                answer, usage = await _a_complete_full(
                    best,
                    messages,
                    client=client,
                    timeout=best.timeout_s,
                    max_tokens=best.max_tokens,
                    retries=1,
                    backoff=0.5,
                    temperature=temp,
                )
            elapsed = (time.monotonic() - t0) * 1000
            return si, FanOutResult(
                worker_id=best.id,
                role=f"self_moa:s{si}",
                answer=answer,
                error=None,
                elapsed_ms=elapsed,
                usage=usage or {},
                ok=True,
            )
        except Exception as e:
            elapsed = (time.monotonic() - t0) * 1000
            return si, FanOutResult(
                worker_id=best.id,
                role=f"self_moa:s{si}",
                answer=None,
                error=str(e),
                elapsed_ms=elapsed,
                usage={},
                ok=False,
            )

    tasks = [asyncio.create_task(_one(i)) for i in range(k)]
    for fut in asyncio.as_completed(tasks):
        si, r = await fut
        results.append((si, r))
        sid = _sample_id(best.id, si)
        yield {
            "_event": "step",
            "candidate": {
                "worker_id": sid,
                "role": f"self_moa:s{si}",
                "answer": r.answer,
                "score": 0.0,
                "score_reason": "",
                "elapsed_ms": int(r.elapsed_ms or 0),
                "error": r.error,
            },
        }

    results.sort(key=lambda x: x[0])

    # ---- score / pick winner ----------------------------------------------
    score_rows: list[dict[str, Any]] = []
    scored: list[tuple[int, FanOutResult, float, str]] = []

    if engine_ok and verifier is not None:
        def _score_all() -> list[tuple[int, FanOutResult, float, str]]:
            out: list[tuple[int, FanOutResult, float, str]] = []
            stats = get_worker_stats()
            for si, r in results:
                sid = _sample_id(best.id, si)
                cs = score_one(
                    verifier,
                    query,
                    CandidateInput(
                        worker_id=sid,
                        answer=r.answer,
                        role=f"self_moa:s{si}",
                        error=r.error,
                        elapsed_ms=float(r.elapsed_ms or 0),
                    ),
                    base_url=ollama_base_url,
                )
                out.append((si, r, float(cs.score), cs.reason or ""))
                if r.ok and r.answer:
                    stats.record_outcome(
                        best.id,
                        score_0_10=float(cs.score),
                        latency_ms=float(r.elapsed_ms) if r.elapsed_ms is not None else None,
                    )
            return out

        scored = await loop.run_in_executor(None, _score_all)
        method = "verifier"
    else:
        # Longest non-empty when engine offline
        for si, r in results:
            if r.ok and r.answer:
                scored.append((si, r, float(len(r.answer)), "longest_fallback"))
            else:
                scored.append(
                    (si, r, 0.0, f"worker failed: {r.error or 'no answer'}")
                )
        method = "longest_fallback"

    for si, r, sc, reason in scored:
        sid = _sample_id(best.id, si)
        score_rows.append({"worker_id": sid, "score": sc, "reason": reason})

    ok_scored = [(si, r, sc, reason) for si, r, sc, reason in scored if r.ok and r.answer]
    if ok_scored:
        winner = max(ok_scored, key=lambda t: (t[2], len(t[1].answer or "")))
        win_si, win_r, win_sc, win_reason = winner
        answer = win_r.answer or ""
        used_fallback = method == "longest_fallback"
    else:
        win_si = 0
        win_r = results[0][1] if results else None
        win_sc = 0.0
        win_reason = "all_samples_failed"
        errs = "; ".join(
            f"s{si}: {r.error or 'no answer'}" for si, r in results
        )
        answer = (
            f"Self-MoA: all {k} samples from {best.id} failed. Details: {errs}"
        )
        used_fallback = True
        method = "all_failed"

    yield {"_event": "scores", "data": score_rows}

    cand_trace = []
    for si, r, sc, reason in scored:
        sid = _sample_id(best.id, si)
        cand_trace.append(
            {
                "worker_id": sid,
                "role": f"self_moa:s{si}",
                "answer": r.answer,
                "score": sc,
                "score_reason": reason,
                "elapsed_ms": int(r.elapsed_ms or 0),
                "error": r.error,
            }
        )

    total_ms = int((time.time() - started) * 1000)
    yield {
        "_event": "done",
        "answer": answer,
        "parallel": {
            "fan_out": cand_trace,
            "final": answer,
            "used_fallback": used_fallback,
            "strategy": "self_moa",
            "method": method,
            "winner": _sample_id(best.id, win_si) if ok_scored else None,
            "winner_score": win_sc if ok_scored else 0.0,
            "winner_reason": win_reason if ok_scored else "all_samples_failed",
            "best_worker": best.id,
            "k": k,
        },
        "usage": _usage(total_ms),
        "degraded": not engine_ok or used_fallback and method == "all_failed",
        "budget_hit": False,
        "path": "fast",
        "orchestration": "self_moa",
        **(
            {"degraded_reason": "engine_unavailable", "missing_engine_models": miss_list}
            if not engine_ok
            else {}
        ),
    }


async def self_moa_fast_events(
    query: str,
    settings: Settings,
    **kwargs: Any,
) -> tuple[dict, list[dict]]:
    """Drain stream into (done_payload, all_events)."""
    events: list[dict] = []
    final: dict = {}
    async for ev in self_moa_fast_stream(query, settings, **kwargs):
        events.append(ev)
        if ev.get("_event") == "done":
            final = {k: v for k, v in ev.items() if k != "_event"}
    return final, events


def _usage(total_ms: int = 0) -> dict:
    return {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": total_ms,
        "orchestration_input_tokens": 0,
        "orchestration_output_tokens": 0,
        "worker_prompt_tokens": 0,
        "worker_completion_tokens": 0,
    }
