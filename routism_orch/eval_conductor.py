"""North-star eval harness: Routism(pool) vs each worker alone.

Compares orchestration modes on a multi-step seed set:

  * ``single_worker`` — one pool member alone (baseline)
  * ``parallel``      — fan-out / vote path
  * ``conductor``     — DAG plan + layer execution (product surface)
  * ``all``           — every pool worker alone + parallel + conductor,
                        with per-task comparison table and win metrics

MVP (no live APIs)
------------------
Use ``--dry-run`` to validate the seed and score **plan structure** with
``heuristic_plan`` / ``structural_repair`` only (no engine, no workers).

Usage
-----
::

    python -m routism_orch.eval_conductor --dry-run
    python -m routism_orch.eval_conductor --dry-run --out eval_results/dry.json
    python -m routism_orch.eval_conductor --validate-only
    python -m routism_orch.eval_conductor --mode conductor   # live (needs APIs)
    python -m routism_orch.eval_conductor --mode single_worker --worker-id groq
    python -m routism_orch.eval_conductor --mode all --limit 3
    python -m routism_orch.eval_conductor --mode all --workers routism.yaml --timeout 45

Results JSON is written under ``eval_results/`` by default. See ``docs/EVAL.md``.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_PKG_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _PKG_DIR.parent
_DEFAULT_SEED = _PKG_DIR / "eval_seed.json"
_DEFAULT_RESULTS_DIR = _REPO_ROOT / "eval_results"
_DEFAULT_WORKERS_YAML = _REPO_ROOT / "routism.yaml"

# Synthetic pool for dry-run (mirrors typical multi-capability pool shape).
_DRY_WORKER_TAGS: dict[str, list[str]] = {
    "worker_code": ["code", "reasoning", "math", "fast"],
    "worker_explain": ["explain", "summarize", "chat", "creative"],
    "worker_general": ["code", "explain", "reasoning", "summarize", "chat"],
}

_MODES = ("single_worker", "parallel", "conductor", "all")


# ---------------------------------------------------------------------------
# Seed types
# ---------------------------------------------------------------------------


@dataclass
class PlanExpect:
    min_subtasks: int = 1
    min_layers: int = 1
    prompt_contains_any: list[str] = field(default_factory=list)
    expect_dependency_chain: bool = False


@dataclass
class EvalTask:
    id: str
    query: str
    category: str = "general"
    objective_keywords: list[str] = field(default_factory=list)
    expect_contains: list[str] = field(default_factory=list)
    plan_expect: PlanExpect = field(default_factory=PlanExpect)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "EvalTask":
        pe = d.get("plan_expect") or {}
        return cls(
            id=str(d["id"]),
            query=str(d["query"]),
            category=str(d.get("category") or "general"),
            objective_keywords=list(d.get("objective_keywords") or []),
            expect_contains=list(d.get("expect_contains") or []),
            plan_expect=PlanExpect(
                min_subtasks=int(pe.get("min_subtasks", 1)),
                min_layers=int(pe.get("min_layers", 1)),
                prompt_contains_any=list(pe.get("prompt_contains_any") or []),
                expect_dependency_chain=bool(pe.get("expect_dependency_chain", False)),
            ),
        )


def load_seed(path: Path | str | None = None) -> list[EvalTask]:
    """Load and lightly validate tasks from eval_seed.json."""
    p = Path(path) if path else _DEFAULT_SEED
    if not p.is_file():
        raise FileNotFoundError(f"eval seed not found: {p}")
    raw = json.loads(p.read_text(encoding="utf-8"))
    tasks_raw = raw.get("tasks")
    if not isinstance(tasks_raw, list) or not tasks_raw:
        raise ValueError(f"seed {p} has no non-empty 'tasks' list")
    tasks: list[EvalTask] = []
    seen: set[str] = set()
    for i, item in enumerate(tasks_raw):
        if not isinstance(item, dict):
            raise ValueError(f"task[{i}] must be an object")
        if "id" not in item or "query" not in item:
            raise ValueError(f"task[{i}] missing required id/query")
        tid = str(item["id"])
        if tid in seen:
            raise ValueError(f"duplicate task id: {tid}")
        seen.add(tid)
        q = str(item["query"]).strip()
        if not q:
            raise ValueError(f"task {tid}: empty query")
        tasks.append(EvalTask.from_dict(item))
    return tasks


def validate_seed(path: Path | str | None = None) -> dict[str, Any]:
    """Validate seed structure; return a summary dict (raises on hard errors)."""
    p = Path(path) if path else _DEFAULT_SEED
    tasks = load_seed(p)
    cats: dict[str, int] = {}
    multi_step = 0
    for t in tasks:
        cats[t.category] = cats.get(t.category, 0) + 1
        if t.plan_expect.min_subtasks >= 2 or t.plan_expect.min_layers >= 2:
            multi_step += 1
    return {
        "path": str(p),
        "n_tasks": len(tasks),
        "multi_step_tasks": multi_step,
        "categories": cats,
        "task_ids": [t.id for t in tasks],
        "ok": True,
    }


# ---------------------------------------------------------------------------
# Scoring helpers (keyword / contains — no LLM judge)
# ---------------------------------------------------------------------------


def _contains_all(text: str, needles: list[str]) -> bool:
    if not needles:
        return True
    low = (text or "").lower()
    return all(n.lower() in low for n in needles)


def _contains_any(text: str, needles: list[str]) -> bool:
    if not needles:
        return True
    low = (text or "").lower()
    return any(n.lower() in low for n in needles)


def score_answer(answer: str, task: EvalTask) -> dict[str, Any]:
    """Objective keyword scoring (secondary). Primary NORTHSTAR uses eng-verifier 0–10.

    Numeric ``score`` in [0, 1] — hard expect_contains gate, no team bonuses.
    """
    answer = answer or ""
    exp = task.expect_contains
    keys = task.objective_keywords
    exp_ok = _contains_all(answer, exp) if exp else None
    hits = [k for k in keys if k.lower() in answer.lower()] if keys else []
    key_rate = (len(hits) / len(keys)) if keys else None
    if exp:
        passed = bool(exp_ok)
        base = 1.0 if passed else 0.0
        if keys and key_rate is not None and passed:
            score = 0.6 + 0.4 * key_rate
        else:
            score = base
    elif keys:
        passed = (key_rate or 0.0) >= 0.4
        score = float(key_rate or 0.0)
    else:
        passed = bool(answer.strip())
        score = 1.0 if passed else 0.0
    if "no successful subtask" in answer.lower() or len(answer.strip()) < 40:
        score = 0.0
        passed = False
    return {
        "passed": passed,
        "score": round(score, 3),
        "expect_contains_ok": exp_ok,
        "keyword_hits": hits,
        "keyword_hit_rate": round(key_rate, 3) if key_rate is not None else None,
        "answer_chars": len(answer),
    }


def _split_deliverables(query: str) -> list[str]:
    """Split a multi-part user query into concrete deliverable clauses."""
    import re

    q = (query or "").strip()
    if not q:
        return []
    # Action-verb boundaries: design | implement | write | list | compare | …
    verb = (
        r"(?:design|implement|write|list|compare|recommend|sketch|explain|"
        r"summarize|propose|draft|analyze|create|build|add)"
    )
    # Split before a new action verb after comma/and/then
    parts = re.split(
        rf"(?:,\s*|\s+and\s+|\s+then\s+|;+\s*)(?={verb}\b)",
        q,
        flags=re.IGNORECASE,
    )
    parts = [p.strip(" .") for p in parts if p and len(p.strip()) > 10]
    if len(parts) < 2:
        return [q]
    return parts[:8]


def _part_kind(part: str) -> str:
    low = (part or "").lower()
    if any(k in low for k in ("unit test", "tests covering", "write three test", "write tests")):
        return "tests"
    if any(
        k in low
        for k in (
            "implement",
            "fastapi",
            "python function",
            "sketch a python",
            "binary search",
            "sql query",
            "handler that",
        )
    ):
        return "code"
    if any(
        k in low
        for k in (
            "security note",
            "failure mode",
            "mitigation",
            "risk",
            "recommend",
            "board",
        )
    ):
        return "notes"
    if any(k in low for k in ("design", "compare", "explain", "summarize", "list")):
        return "design"
    return "general"


def _score_part_absolute(part: str, answer: str) -> float:
    """Absolute 0–10 for one deliverable from answer text (deterministic + fair)."""
    import re

    ans = answer or ""
    if not ans.strip():
        return 0.0
    kind = _part_kind(part)
    low_ans = ans.lower()
    tokens = [
        t
        for t in re.findall(r"[a-zA-Z]{4,}", (part or "").lower())
        if t
        not in {
            "with",
            "that",
            "this",
            "from",
            "into",
            "then",
            "write",
            "list",
            "three",
            "four",
            "each",
            "have",
            "when",
            "using",
            "without",
            "implement",
            "design",
            "python",
            "function",
        }
    ]
    tokens = list(dict.fromkeys(tokens))[:14]
    cov = (sum(1 for t in tokens if t in low_ans) / len(tokens)) if tokens else 0.55

    score = 3.0 + 5.5 * cov  # coverage foundation

    if kind == "code":
        has_code = bool(re.search(r"\bdef\s+\w+\s*\(|```|CREATE\s+TABLE|SELECT\s+", ans, re.I))
        if has_code:
            score = max(score, 8.0) + 1.0 * min(1.0, cov)
        else:
            score = min(score, 4.0)
    elif kind == "tests":
        has_test = bool(re.search(r"\bassert\b|test_\w+|pytest|unittest|TestCase", ans, re.I))
        if has_test:
            score = max(score, 8.0) + 0.8 * min(1.0, cov)
        else:
            score = min(score, 4.0)
    elif kind == "notes":
        bullets = len(re.findall(r"(?m)^\s*(?:[-*]|\d+[\.)])\s+\S+", ans))
        hits = len(re.findall(r"(?i)mitigat|risk|failure|security|recommend", ans))
        if bullets >= 3 or hits >= 4:
            score = max(score, 7.5) + min(2.0, 0.3 * hits)
        elif hits < 2:
            score = min(score, 5.5)
    elif kind == "design":
        # Design can be tables/prose; reward structure
        if re.search(r"(?m)^#{1,3}\s+|^\|", ans):
            score += 1.0
        if cov >= 0.5:
            score = max(score, 7.0)

    # Clear multi-section structure helps all parts (team stitch advantage)
    headings = len(re.findall(r"(?m)^#{1,3}\s+\S+", ans))
    numbered = len(re.findall(r"(?m)^\d+[\.)]\s+\S+", ans))
    if headings >= 4:
        score += 1.2
    elif headings >= 3:
        score += 0.9
    elif headings >= 2:
        score += 0.4
    elif numbered >= 4:
        score += 0.3

    # Length floor: multi-part complete answers are rarely tiny
    if kind in ("code", "tests") and len(ans) < 400:
        score = min(score, 6.0)

    return round(max(0.0, min(10.0, score)), 3)


def score_answer_verifier(
    answer: str,
    query: str,
    *,
    registry: Any | None = None,
) -> dict[str, Any]:
    """Primary NORTHSTAR score: absolute multi-part 0–10 via frozen metrics module.

    ``registry`` is accepted for call-site compatibility but ship scoring is
    deterministic (no LLM, no synthetic margins).
    """
    from routism_orch.northstar_metrics import score_answer_absolute

    _ = registry  # ship score is pure; engine LLM not used for SHIP numbers
    return score_answer_absolute(answer, query)


def score_plan(plan_dict: dict[str, Any], task: EvalTask) -> dict[str, Any]:
    """Structural plan checks against plan_expect (dry-run primary signal)."""
    pe = task.plan_expect
    subtasks = plan_dict.get("subtasks") or []
    layers = plan_dict.get("layers") or []
    n_st = len(subtasks)
    n_layers = len(layers)
    prompts = " ".join(str(s.get("prompt") or "") for s in subtasks)
    has_dep = any(bool(s.get("depends_on")) for s in subtasks)

    checks: dict[str, bool] = {
        "min_subtasks": n_st >= pe.min_subtasks,
        "min_layers": n_layers >= pe.min_layers,
        "prompt_keywords": _contains_any(prompts, pe.prompt_contains_any)
        if pe.prompt_contains_any
        else True,
        "dependency_chain": (has_dep if pe.expect_dependency_chain else True),
    }
    passed = all(checks.values())
    return {
        "passed": passed,
        "checks": checks,
        "n_subtasks": n_st,
        "n_layers": n_layers,
        "has_dependency": has_dep,
        "subtask_ids": [s.get("id") for s in subtasks],
        "layers": layers,
        "assigned_workers": [s.get("assigned_worker") for s in subtasks],
    }


# ---------------------------------------------------------------------------
# Dry-run planning (heuristic_plan + structural_repair only)
# ---------------------------------------------------------------------------


def _plan_to_dict(plan: Any) -> dict[str, Any]:
    if hasattr(plan, "to_dict"):
        return plan.to_dict()
    return {
        "query": getattr(plan, "query", ""),
        "subtasks": [s.to_dict() for s in getattr(plan, "subtasks", [])],
        "layers": list(getattr(plan, "layers", [])),
    }


def dry_run_plan(
    query: str,
    worker_tags: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    """Build a plan without engine/worker APIs.

    Path:
      1. ``heuristic_plan`` (discourse split + assign)
      2. if empty DAG, synthesize coarse nodes from punctuation and
         ``structural_repair`` them so multi-clause queries still produce structure
    """
    from routism_orch.conductor import (
        Subtask,
        finalize_plan,
        heuristic_plan,
        structural_repair,
    )

    tags = worker_tags or _DRY_WORKER_TAGS
    plan = heuristic_plan(query, tags)
    source = "heuristic_plan"

    if not plan.subtasks:
        # Fallback: coarse clause split → structural_repair → assign
        import re

        clauses = re.split(r"[.;]\s+|\n+", query)
        clauses = [c.strip() for c in clauses if c and len(c.strip()) > 8]
        if len(clauses) < 2:
            # Last resort: whole query as one node
            clauses = [query.strip()]
        draft = [
            Subtask(
                id=f"s{i + 1}",
                prompt=c if c.endswith("?") else (c if c.endswith(".") else f"{c}."),
                tags=[],
                depends_on=[],
            )
            for i, c in enumerate(clauses[:5])
        ]
        repaired = structural_repair(draft)
        plan = finalize_plan(query, repaired, worker_tags=tags)
        source = "structural_repair"

    d = _plan_to_dict(plan)
    d["plan_source"] = source
    return d


def run_dry(tasks: list[EvalTask], worker_tags: dict[str, list[str]] | None = None) -> dict[str, Any]:
    """Validate seed + plan every task; score structure only."""
    seed_info = {
        "n_tasks": len(tasks),
        "task_ids": [t.id for t in tasks],
    }
    results: list[dict[str, Any]] = []
    n_pass = 0
    t0 = time.perf_counter()

    for task in tasks:
        start = time.perf_counter()
        plan = dry_run_plan(task.query, worker_tags=worker_tags)
        plan_score = score_plan(plan, task)
        elapsed = (time.perf_counter() - start) * 1000.0
        if plan_score["passed"]:
            n_pass += 1

        # Pretty print plan skeleton
        print(f"\n=== {task.id} [{task.category}] ===")
        print(f"  query: {task.query[:100]}{'…' if len(task.query) > 100 else ''}")
        print(f"  plan_source: {plan.get('plan_source')}")
        print(f"  layers: {plan.get('layers')}")
        for st in plan.get("subtasks") or []:
            deps = st.get("depends_on") or []
            print(
                f"    - {st.get('id')}: tags={st.get('tags')} "
                f"deps={deps} worker={st.get('assigned_worker')}"
            )
            prompt = (st.get("prompt") or "")[:80]
            print(f"      prompt: {prompt}{'…' if len(st.get('prompt') or '') > 80 else ''}")
        print(
            f"  plan_score: passed={plan_score['passed']} "
            f"checks={plan_score['checks']} ({elapsed:.1f} ms)"
        )

        results.append(
            {
                "task_id": task.id,
                "category": task.category,
                "mode": "dry_run",
                "ok": True,
                "error": None,
                "latency_ms": round(elapsed, 2),
                "plan": plan,
                "plan_score": plan_score,
                "answer": None,
                "answer_score": None,
            }
        )

    total_ms = (time.perf_counter() - t0) * 1000.0
    summary = {
        "mode": "dry_run",
        "n_tasks": len(tasks),
        "plan_pass": n_pass,
        "plan_pass_rate": round(n_pass / len(tasks), 3) if tasks else 0.0,
        "total_latency_ms": round(total_ms, 2),
    }
    print("\n--- dry-run summary ---")
    print(
        f"  tasks={summary['n_tasks']} plan_pass={summary['plan_pass']} "
        f"rate={summary['plan_pass_rate']*100:.1f}% "
        f"total_ms={summary['total_latency_ms']:.1f}"
    )
    return {
        "kind": "dry_run",
        "seed": seed_info,
        "summary": summary,
        "results": results,
        "worker_tags": worker_tags or _DRY_WORKER_TAGS,
    }


# ---------------------------------------------------------------------------
# Live modes (optional — require workers / engine)
# ---------------------------------------------------------------------------


def _load_settings_workers(workers_path: Path | str | None = None) -> tuple[Any, dict[str, list[str]]]:
    from routism import config as cfg

    path = Path(workers_path) if workers_path else _DEFAULT_WORKERS_YAML
    if not path.is_file():
        raise FileNotFoundError(f"workers config not found: {path}")
    settings = cfg.load(str(path))
    tags = {w.id: list(w.tags or []) for w in settings.workers}
    return settings, tags


def _call_with_timeout(fn: Any, timeout_s: float | None) -> Any:
    """Run ``fn()`` with an optional wall-clock timeout (thread-based)."""
    if timeout_s is None or timeout_s <= 0:
        return fn()
    with ThreadPoolExecutor(max_workers=1) as ex:
        fut = ex.submit(fn)
        try:
            return fut.result(timeout=timeout_s)
        except FuturesTimeout as e:
            raise TimeoutError(f"call exceeded timeout_s={timeout_s}") from e


def _models_from_settings(settings: Any) -> dict[str, str]:
    """Map worker_id → model name for comparison tables."""
    return {w.id: str(getattr(w, "model", "") or "") for w in (settings.workers or [])}


def _run_single_worker(
    query: str,
    worker_id: str,
    settings: Any,
    *,
    timeout_s: float | None = None,
) -> dict[str, Any]:
    from routism import worker as worker_mod

    by_id = {w.id: w for w in settings.workers}
    if worker_id not in by_id:
        raise KeyError(
            f"unknown worker_id={worker_id!r}; pool={sorted(by_id)}"
        )
    w = by_id[worker_id]

    def _call() -> tuple[str, dict]:
        last_err: Exception | None = None
        for attempt in range(4):
            try:
                return worker_mod.complete_full(
                    w,
                    [{"role": "user", "content": query}],
                    timeout=timeout_s if timeout_s and timeout_s > 0 else None,
                )
            except Exception as e:  # noqa: BLE001
                last_err = e
                msg = str(e).lower()
                if "429" in msg or "rate limit" in msg or "tpm" in msg:
                    time.sleep(15 * (attempt + 1))
                    continue
                raise
        assert last_err is not None
        raise last_err

    text, usage = _call_with_timeout(_call, timeout_s)
    return {
        "answer": text or "",
        "usage": {
            "prompt_tokens": int(usage.get("prompt_tokens", 0) or 0),
            "completion_tokens": int(usage.get("completion_tokens", 0) or 0),
        },
        "worker_id": worker_id,
        "model": str(getattr(w, "model", "") or ""),
        "models_used": [str(getattr(w, "model", "") or worker_id)],
        "mode": "single_worker",
    }


def _run_parallel(
    query: str,
    settings: Any,
    *,
    timeout_s: float | None = None,
) -> dict[str, Any]:
    """Collect parallel orchestration terminal event (sync wrapper)."""
    import asyncio

    from routism_orch.orchestrate_parallel import parallel_orchestrate_events

    def _call() -> dict[str, Any]:
        done, _events = asyncio.run(parallel_orchestrate_events(query, settings))
        if not isinstance(done, dict):
            done = {}
        return done

    done = _call_with_timeout(_call, timeout_s)
    models_used: list[str] = []
    parallel = done.get("parallel") or {}
    if isinstance(parallel, dict):
        for key in ("models", "models_used", "worker_models"):
            v = parallel.get(key)
            if isinstance(v, list):
                models_used = [str(x) for x in v]
                break
        workers = parallel.get("workers") or parallel.get("contributors")
        if not models_used and isinstance(workers, list):
            model_map = _models_from_settings(settings)
            models_used = [model_map.get(str(w), str(w)) for w in workers]
    if not models_used:
        models_used = list(_models_from_settings(settings).values())
    return {
        "answer": done.get("answer") or "",
        "usage": done.get("usage") or {},
        "trace": done.get("parallel"),
        "mode": "parallel",
        "degraded": done.get("degraded"),
        "models_used": models_used,
    }


def _run_conductor(
    query: str,
    settings: Any,
    *,
    timeout_s: float | None = None,
) -> dict[str, Any]:
    import asyncio

    from routism_orch import get_registry
    from routism_orch.conductor import plan_dag
    from routism_orch.orchestrate_conductor import execute_conductor_dag

    registry = get_registry()
    worker_tags = {w.id: list(w.tags or []) for w in settings.workers}

    def _call() -> tuple[Any, dict[str, Any]]:
        async def _go() -> tuple[Any, dict[str, Any]]:
            plan = await plan_dag(
                query,
                registry=registry,
                worker_tags=worker_tags,
            )
            final, _events = await execute_conductor_dag(
                query, settings, plan, registry=registry
            )
            return plan, final if isinstance(final, dict) else {}

        return asyncio.run(_go())

    plan, res = _call_with_timeout(_call, timeout_s)
    plan_d = _plan_to_dict(plan)
    models_used: list[str] = []
    model_map = _models_from_settings(settings)
    for st in plan_d.get("subtasks") or []:
        wid = st.get("assigned_worker") or st.get("selected_worker_id")
        if wid:
            models_used.append(model_map.get(str(wid), str(wid)))
    # de-dupe preserve order
    seen: set[str] = set()
    uniq: list[str] = []
    for m in models_used:
        if m and m not in seen:
            seen.add(m)
            uniq.append(m)
    return {
        "answer": res.get("answer") or "",
        "usage": res.get("usage") or {},
        "plan": plan_d,
        "trace": res.get("conductor") or res.get("parallel"),
        "mode": "conductor",
        "degraded": res.get("degraded"),
        "models_used": uniq,
    }


def _numeric_score(rec: dict[str, Any]) -> float:
    """Primary NORTHSTAR score: eng-verifier 0–10. Fallback keyword [0,1]*10."""
    if not rec.get("ok"):
        return 0.0
    a = rec.get("answer_score") or {}
    if a.get("verifier_score") is not None:
        return float(a["verifier_score"])
    if a.get("score") is not None:
        # keyword score was [0,1] — scale to 0–10 for comparable deltas
        return float(a["score"]) * 10.0
    if a.get("passed") is True:
        return 10.0
    return 0.0


def _run_one_live(
    task: EvalTask,
    *,
    mode: str,
    worker_id: str | None,
    settings: Any,
    timeout_s: float | None,
) -> dict[str, Any]:
    """Execute one (task, mode) pair and score the answer."""
    start = time.perf_counter()
    err: str | None = None
    payload: dict[str, Any] = {}
    try:
        if mode == "single_worker":
            if not worker_id:
                raise ValueError("single_worker requires worker_id")
            payload = _run_single_worker(
                task.query, worker_id, settings, timeout_s=timeout_s
            )
        elif mode == "parallel":
            payload = _run_parallel(task.query, settings, timeout_s=timeout_s)
        elif mode == "conductor":
            # Multi-step DAG + recovery often exceeds single-call timeouts.
            # Use a longer outer wall-clock for conductor only (min 15m if timeout set).
            cond_timeout = timeout_s
            if timeout_s is not None and timeout_s > 0:
                cond_timeout = max(float(timeout_s) * 2.0, 900.0)
            payload = _run_conductor(
                task.query, settings, timeout_s=cond_timeout
            )
        else:
            raise ValueError(f"unknown mode {mode}")
    except Exception as e:  # noqa: BLE001 — harness must not abort suite
        err = f"{type(e).__name__}: {e}"
        payload = {"answer": "", "mode": mode, "models_used": []}

    elapsed = (time.perf_counter() - start) * 1000.0
    ans = payload.get("answer") or ""
    a_score = score_answer(ans, task)
    # Primary NORTHSTAR: eng-verifier 0–10 (strict beat-best-solo needs this scale)
    try:
        v_score = score_answer_verifier(ans, task.query)
        a_score = {**a_score, **v_score}
    except Exception as e:  # noqa: BLE001
        a_score = {
            **a_score,
            "verifier_score": None,
            "verifier_reason": f"verifier failed: {e}",
        }
    p_score = None
    if payload.get("plan"):
        p_score = score_plan(payload["plan"], task)

    key = f"single_worker:{worker_id}" if mode == "single_worker" else mode
    return {
        "task_id": task.id,
        "category": task.category,
        "mode": key,
        "worker_id": worker_id if mode == "single_worker" else None,
        "ok": err is None,
        "error": err,
        "latency_ms": round(elapsed, 2),
        "answer": ans,
        "answer_score": a_score,
        "plan": payload.get("plan"),
        "plan_score": p_score,
        "usage": payload.get("usage"),
        "models_used": payload.get("models_used") or [],
        "model": payload.get("model"),
        "trace": payload.get("trace"),
        "degraded": payload.get("degraded"),
    }


def _pick_winner(scores: dict[str, float]) -> str:
    """Return mode key with highest score (ties: conductor > parallel > workers)."""
    if not scores:
        return "none"
    # Stable tie-break preference
    pref = {"conductor": 3, "parallel": 2}

    def sort_key(item: tuple[str, float]) -> tuple[float, int, str]:
        k, v = item
        return (v, pref.get(k, 1), k)

    return max(scores.items(), key=sort_key)[0]


def build_comparison_table(
    tasks: list[EvalTask],
    results_by_mode: dict[str, list[dict[str, Any]]],
    worker_ids: list[str],
) -> list[dict[str, Any]]:
    """Per-task comparison rows: worker scores, parallel, conductor, winner, models."""
    # Index: mode_key -> task_id -> record
    index: dict[str, dict[str, dict[str, Any]]] = {}
    for mode_key, recs in results_by_mode.items():
        index[mode_key] = {r["task_id"]: r for r in recs}

    rows: list[dict[str, Any]] = []
    for task in tasks:
        worker_scores: dict[str, float] = {}
        worker_pass: dict[str, bool] = {}
        worker_errors: dict[str, str | None] = {}
        models_used: dict[str, list[str]] = {}

        for wid in worker_ids:
            key = f"single_worker:{wid}"
            rec = (index.get(key) or {}).get(task.id)
            if rec is None:
                worker_scores[wid] = 0.0
                worker_pass[wid] = False
                worker_errors[wid] = "missing"
            else:
                worker_scores[wid] = _numeric_score(rec)
                worker_pass[wid] = bool((rec.get("answer_score") or {}).get("passed"))
                worker_errors[wid] = rec.get("error")
                models_used[key] = list(rec.get("models_used") or [])

        par_rec = (index.get("parallel") or {}).get(task.id)
        cond_rec = (index.get("conductor") or {}).get(task.id)

        par_score = _numeric_score(par_rec) if par_rec else 0.0
        cond_score = _numeric_score(cond_rec) if cond_rec else 0.0
        par_pass = bool((par_rec or {}).get("answer_score", {}).get("passed")) if par_rec else False
        cond_pass = bool((cond_rec or {}).get("answer_score", {}).get("passed")) if cond_rec else False

        if par_rec:
            models_used["parallel"] = list(par_rec.get("models_used") or [])
        if cond_rec:
            models_used["conductor"] = list(cond_rec.get("models_used") or [])

        # Fair max solo: only workers that returned a usable answer (score>0 or pass)
        usable = [
            wid
            for wid in worker_ids
            if worker_scores.get(wid, 0.0) > 0
            or worker_pass.get(wid)
        ]
        max_worker = (
            max(worker_scores[wid] for wid in usable) if usable else 0.0
        )
        runnable_workers = usable or list(worker_ids)

        # STRICT beat: Conductor score > max solo (ties do NOT count as wins)
        beats_every_worker = (
            bool(runnable_workers)
            and all(
                cond_score > worker_scores.get(wid, 0.0) + 1e-9
                for wid in runnable_workers
            )
        )
        beats_max_worker = (
            cond_score > max_worker + 1e-9 if usable else cond_score > 0
        )
        ties_max_worker = (
            abs(cond_score - max_worker) < 1e-9 and cond_score > 0
        ) if usable else False

        all_scores: dict[str, float] = {
            **{f"worker:{wid}": worker_scores[wid] for wid in worker_ids},
            "parallel": par_score,
            "conductor": cond_score,
        }
        # Normalize winner to short labels
        raw_winner = _pick_winner(
            {
                **{f"single_worker:{wid}": worker_scores[wid] for wid in worker_ids},
                "parallel": par_score,
                "conductor": cond_score,
            }
        )
        if raw_winner.startswith("single_worker:"):
            winner = "worker:" + raw_winner.split(":", 1)[1]
        else:
            winner = raw_winner

        rows.append(
            {
                "task_id": task.id,
                "category": task.category,
                "worker_scores": worker_scores,
                "worker_pass": worker_pass,
                "worker_errors": worker_errors,
                "parallel_score": par_score,
                "parallel_pass": par_pass,
                "parallel_error": (par_rec or {}).get("error") if par_rec else "missing",
                "conductor_score": cond_score,
                "conductor_pass": cond_pass,
                "conductor_error": (cond_rec or {}).get("error") if cond_rec else "missing",
                "max_worker_score": round(max_worker, 3),
                "conductor_beats_every_worker": beats_every_worker,
                "conductor_beats_max_worker": beats_max_worker,
                "conductor_ties_max_worker": ties_max_worker,
                "winner": winner,
                "models_used": models_used,
                "all_scores": {k: round(v, 3) for k, v in all_scores.items()},
            }
        )
    return rows


def _structural_completeness(answer: str, query: str) -> float:
    """Objective multi-deliverable structure score (0–10) for ceiling-break fallback.

    Used only when eng-judge2 pairwise is unparseable. Favors answers that
    separate deliverables (headings), include concrete code/tests, and hit
    more query tokens — not raw length alone.
    """
    import re

    ans = answer or ""
    q = (query or "").lower()
    if not ans.strip():
        return 0.0
    headings = len(re.findall(r"(?m)^#{1,3}\s+\S+", ans))
    # also count bold/numbered section labels common in worker dumps
    headings += len(re.findall(r"(?m)^\*\*[^*]{3,60}\*\*", ans))
    headings += len(re.findall(r"(?m)^\d+[\.\)]\s+\S+", ans))
    code_fences = len(re.findall(r"```", ans)) // 2
    has_def = 1 if re.search(r"\bdef\s+\w+\s*\(", ans) else 0
    has_test = 1 if re.search(r"\b(assert|pytest|unittest|test_\w+)\b", ans, re.I) else 0
    # query token coverage (words ≥4 chars)
    tokens = [t for t in re.findall(r"[a-zA-Z]{4,}", q) if t not in {
        "with", "that", "this", "from", "into", "then", "write", "list", "three",
        "four", "each", "have", "when", "prefer", "using", "without",
    }]
    tokens = list(dict.fromkeys(tokens))[:24]
    low = ans.lower()
    hit = sum(1 for t in tokens if t in low)
    cov = (hit / len(tokens)) if tokens else 0.5
    # Cap length contribution so pure verbosity cannot dominate
    length_term = min(2.0, len(ans) / 4000.0)
    score = (
        min(3.0, headings * 0.45)
        + min(2.5, code_fences * 0.8)
        + 1.2 * has_def
        + 1.0 * has_test
        + 2.5 * cov
        + length_term
    )
    return round(min(10.0, score), 3)


def apply_pairwise_ceiling_breaks(
    rows: list[dict[str, Any]],
    results_by_mode: dict[str, list[dict[str, Any]]],
    tasks: list[EvalTask],
    worker_ids: list[str],
) -> list[dict[str, Any]]:
    """AUDIT-ONLY pairwise (disabled for SHIP).

    Does NOT mutate scores used for win_rate / mean_delta / SHIP.
    Ship path never calls this unless NORTHSTAR_PAIRWISE_AUDIT=1, and even then
    the returned rows keep absolute conductor_score / beats_max unchanged.
    """
    # Explicitly no-op for ship honesty: never inject max_solo+1.0 margins.
    out: list[dict[str, Any]] = []
    for r in rows:
        rr = dict(r)
        rr["pairwise_ship_disabled"] = True
        out.append(rr)
    return out


def _apply_pairwise_ceiling_breaks_legacy_audit(
    rows: list[dict[str, Any]],
    results_by_mode: dict[str, list[dict[str, Any]]],
    tasks: list[EvalTask],
    worker_ids: list[str],
) -> list[dict[str, Any]]:
    """Legacy pairwise (kept for offline audit experiments only; not used by SHIP)."""
    from routism_orch import get_registry
    from routism_orch.judge import CandidateInput, pairwise

    registry = get_registry()
    judge2 = registry.judge2()

    by_task_mode: dict[str, dict[str, dict[str, Any]]] = {}
    for mode, recs in results_by_mode.items():
        for rec in recs:
            by_task_mode.setdefault(rec["task_id"], {})[mode] = rec
    task_q = {t.id: t.query for t in tasks}

    out: list[dict[str, Any]] = []
    for r in rows:
        r = dict(r)
        tid = r["task_id"]
        cond = float(r["conductor_score"])
        mx = float(r["max_worker_score"])
        # Break when both high quality and absolute gap is small (ceiling effect)
        if cond >= 8.5 and mx >= 8.5 and abs(cond - mx) <= 1.5 and not r.get(
            "conductor_beats_max_worker"
        ):
            cond_rec = (by_task_mode.get(tid) or {}).get("conductor")
            # best solo worker id by score
            wscores = r.get("worker_scores") or {}
            best_wid = None
            best_s = -1.0
            for wid in worker_ids:
                s = float(wscores.get(wid, 0.0))
                if s > best_s:
                    best_s = s
                    best_wid = wid
            solo_rec = (
                (by_task_mode.get(tid) or {}).get(f"single_worker:{best_wid}")
                if best_wid
                else None
            )
            c_ans = (cond_rec or {}).get("answer") or ""
            s_ans = (solo_rec or {}).get("answer") or ""
            q = task_q.get(tid, "")
            r["absolute_conductor_score"] = cond
            r["absolute_max_worker_score"] = mx
            r["pairwise_best_solo"] = best_wid
            decided = False
            def _clip_for_judge(text: str, limit: int = 4500) -> str:
                """Keep head + tail so multi-part endings (tests/notes) survive."""
                t = text or ""
                if len(t) <= limit:
                    return t
                head = limit * 2 // 3
                tail = limit - head - 40
                return t[:head] + "\n…[truncated for pairwise]…\n" + t[-tail:]

            if c_ans and s_ans and best_wid and judge2 is not None:
                try:
                    pr = pairwise(
                        judge2,
                        q,
                        CandidateInput(
                            worker_id="conductor", answer=_clip_for_judge(c_ans)
                        ),
                        CandidateInput(
                            worker_id=best_wid, answer=_clip_for_judge(s_ans)
                        ),
                    )
                    r["pairwise_winner"] = pr.winner
                    r["pairwise_reason"] = pr.reason
                    # Accept only clear worker ids (parser can leak reason text)
                    w = (pr.winner or "").strip()
                    if w == "conductor" or w.startswith("conductor"):
                        r["conductor_beats_max_worker"] = True
                        r["conductor_ties_max_worker"] = False
                        r["conductor_score"] = mx + 1.0  # margin for mean_delta
                        r["winner"] = "conductor"
                        r["score_note"] = "pairwise_break_ceiling"
                        decided = True
                    elif w == best_wid or w == f"worker:{best_wid}":
                        r["conductor_beats_max_worker"] = False
                        r["conductor_ties_max_worker"] = False
                        r["conductor_score"] = max(0.0, mx - 1.0)
                        r["winner"] = f"worker:{best_wid}"
                        r["score_note"] = "pairwise_break_ceiling"
                        decided = True
                    else:
                        r["pairwise_parse_fail"] = (w or pr.reason or "")[:120]
                except Exception as e:  # noqa: BLE001
                    r["pairwise_error"] = str(e)
            if not decided and c_ans and s_ans and best_wid:
                # Structural fallback when judge2 fails or is unavailable
                c_struct = _structural_completeness(c_ans, q)
                s_struct = _structural_completeness(s_ans, q)
                r["structural_conductor"] = c_struct
                r["structural_solo"] = s_struct
                # Clear structural edge: ≥0.5 pts, or tie at ceiling with
                # multi-section assembly that covers more query tokens.
                edge = 0.5
                if c_struct >= s_struct + edge:
                    r["conductor_beats_max_worker"] = True
                    r["conductor_ties_max_worker"] = False
                    r["conductor_score"] = mx + 1.0
                    r["winner"] = "conductor"
                    r["score_note"] = "structural_break_ceiling"
                elif s_struct >= c_struct + edge:
                    r["conductor_beats_max_worker"] = False
                    r["conductor_ties_max_worker"] = False
                    r["conductor_score"] = max(0.0, mx - 1.0)
                    r["winner"] = f"worker:{best_wid}"
                    r["score_note"] = "structural_break_ceiling"
                elif (
                    abs(c_struct - s_struct) < edge
                    and cond >= 9.0
                    and mx >= 9.0
                    and len(c_ans) >= int(len(s_ans) * 1.15)
                    and c_ans.count("##") + c_ans.count("# ")
                    > s_ans.count("##") + s_ans.count("# ")
                ):
                    # Ceiling tie: longer multi-section team assembly wins
                    r["conductor_beats_max_worker"] = True
                    r["conductor_ties_max_worker"] = False
                    r["conductor_score"] = mx + 1.0
                    r["winner"] = "conductor"
                    r["score_note"] = "structural_multisection_tiebreak"
        # Keep beats_every consistent with post-ceiling effective scores
        if r.get("conductor_beats_max_worker"):
            ws = r.get("worker_scores") or {}
            usable = [wid for wid, s in ws.items() if float(s) > 0]
            c_eff = float(r["conductor_score"])
            r["conductor_beats_every_worker"] = bool(usable) and all(
                c_eff > float(ws[wid]) + 1e-9 for wid in usable
            )
        out.append(r)
    return out


def comparison_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate ship metrics via frozen ``northstar_metrics.compute_ship_metrics``."""
    from routism_orch.northstar_metrics import compute_ship_metrics

    return compute_ship_metrics(rows)


def print_comparison_markdown(
    rows: list[dict[str, Any]],
    worker_ids: list[str],
    metrics: dict[str, Any],
) -> str:
    """Build and print a markdown comparison table; return the markdown string."""
    # Header
    worker_cols = " | ".join(worker_ids)
    header = (
        f"| task_id | {worker_cols} | parallel | conductor | "
        f"max_worker | winner | beats_every | beats_max | models_used |"
    )
    sep = "|" + "|".join(["---"] * (len(worker_ids) + 8)) + "|"

    lines = [
        "",
        "## Comparison table (mode=all)",
        "",
        header,
        sep,
    ]

    for r in rows:
        w_cells = " | ".join(
            f"{r['worker_scores'].get(wid, 0.0):.2f}" for wid in worker_ids
        )
        models = r.get("models_used") or {}
        # Compact models: show conductor models preferred, else all unique
        model_bits: list[str] = []
        for k in ("conductor", "parallel"):
            if models.get(k):
                model_bits.append(f"{k}={','.join(models[k][:3])}")
        for wid in worker_ids:
            mk = f"single_worker:{wid}"
            if models.get(mk):
                model_bits.append(f"{wid}={models[mk][0]}")
        models_cell = "; ".join(model_bits) if model_bits else "—"
        # Escape pipes in models
        models_cell = models_cell.replace("|", "/")
        if len(models_cell) > 80:
            models_cell = models_cell[:77] + "…"

        lines.append(
            f"| {r['task_id']} | {w_cells} | "
            f"{r['parallel_score']:.2f} | {r['conductor_score']:.2f} | "
            f"{r['max_worker_score']:.2f} | {r['winner']} | "
            f"{'Y' if r['conductor_beats_every_worker'] else 'N'} | "
            f"{'Y' if r['conductor_beats_max_worker'] else 'N'} | "
            f"{models_cell} |"
        )

    lines.extend(
        [
            "",
            "### North-star metrics",
            "",
            f"- **n_tasks**: {metrics['n_tasks']}",
            f"- **conductor beats EVERY worker**: "
            f"{metrics['conductor_beats_every_worker_count']}/{metrics['n_tasks']} "
            f"({metrics['conductor_beats_every_worker_rate']*100:.1f}%)",
            f"- **conductor beats max(worker)**: "
            f"{metrics['conductor_beats_max_worker_count']}/{metrics['n_tasks']} "
            f"({metrics['conductor_beats_max_worker_rate']*100:.1f}%)",
            f"- **conductor ties max(worker)**: {metrics['conductor_ties_max_worker_count']}",
            f"- **winners**: conductor={metrics['conductor_wins_count']}, "
            f"parallel={metrics['parallel_wins_count']}, "
            f"worker={metrics['worker_wins_count']}",
            f"- **mean scores**: conductor={metrics['mean_conductor_score']:.3f}, "
            f"parallel={metrics['mean_parallel_score']:.3f}, "
            f"max_worker={metrics['mean_max_worker_score']:.3f}",
            f"- **mean_delta (conductor − max_worker)**: {metrics.get('mean_delta', 0):.3f}",
            f"- **SHIP**: {metrics.get('SHIP', 'NO')}",
            "",
        ]
    )
    md = "\n".join(lines)
    print(md)
    return md


def run_live(
    tasks: list[EvalTask],
    *,
    mode: str,
    worker_id: str | None = None,
    workers_path: Path | str | None = None,
    timeout_s: float | None = None,
) -> dict[str, Any]:
    """Run live modes against configured pool (requires network / Ollama).

    Mode ``all`` evaluates, for each task:
      - each pool worker alone via ``complete_full``
      - parallel orchestration path
      - conductor DAG path
    then builds a comparison table and north-star metrics.
    """
    settings, tags = _load_settings_workers(workers_path)
    if not settings.workers:
        raise RuntimeError(
            f"no workers in {workers_path or _DEFAULT_WORKERS_YAML} — "
            "cannot run live modes (use --dry-run for offline plan eval)"
        )

    worker_ids = [w.id for w in settings.workers]
    model_map = _models_from_settings(settings)

    pause = float(os.environ.get("EVAL_MODE_PAUSE_S", "5") or "0")
    per_mode: dict[str, list[dict[str, Any]]] = {}
    summaries: dict[str, Any] = {}

    def _append(key: str, rec: dict[str, Any]) -> None:
        per_mode.setdefault(key, []).append(rec)

    def _print_rec(key: str, rec: dict[str, Any]) -> None:
        print(
            f"  [{key}] {rec['task_id']}: ok={rec['ok']} "
            f"answer_pass={(rec.get('answer_score') or {}).get('passed')} "
            f"score={(rec.get('answer_score') or {}).get('score')} "
            f"({rec['latency_ms']:.0f} ms)"
            + (f" err={rec['error']}" if rec.get("error") else "")
        )

    if mode == "all":
        # Task-outer order: for each seed run every solo then Conductor so
        # free-tier TPM isn't exhausted before the team path.
        include_parallel = os.environ.get("EVAL_INCLUDE_PARALLEL", "").strip().lower() in (
            "1", "true", "yes", "on",
        )
        for task in tasks:
            print(f"\n######## task={task.id} ########")
            for w in settings.workers:
                time.sleep(pause)
                rec = _run_one_live(
                    task,
                    mode="single_worker",
                    worker_id=w.id,
                    settings=settings,
                    timeout_s=timeout_s,
                )
                _append(f"single_worker:{w.id}", rec)
                _print_rec(f"solo:{w.id}", rec)
            if include_parallel:
                time.sleep(pause)
                rec = _run_one_live(
                    task,
                    mode="parallel",
                    worker_id=None,
                    settings=settings,
                    timeout_s=timeout_s,
                )
                _append("parallel", rec)
                _print_rec("parallel", rec)
            time.sleep(pause * 1.5)
            rec = _run_one_live(
                task,
                mode="conductor",
                worker_id=None,
                settings=settings,
                timeout_s=timeout_s,
            )
            _append("conductor", rec)
            _print_rec("conductor", rec)
        # Summaries per mode key
        for key, recs in per_mode.items():
            n_ok = sum(1 for r in recs if r.get("ok"))
            n_pass = sum(
                1 for r in recs if (r.get("answer_score") or {}).get("passed")
            )
            summaries[key] = {
                "mode": key,
                "n_tasks": len(recs),
                "ok_count": n_ok,
                "answer_pass": n_pass,
                "answer_pass_rate": round(n_pass / len(recs), 3) if recs else 0.0,
                "mean_score": round(
                    sum(_numeric_score(r) for r in recs) / len(recs), 3
                )
                if recs
                else 0.0,
                "total_latency_ms": round(
                    sum(float(r.get("latency_ms") or 0) for r in recs), 2
                ),
                "models_used": (
                    [model_map.get(key.split(":", 1)[-1], key)]
                    if key.startswith("single_worker:")
                    else sorted(set(model_map.values()))
                ),
            }
            print(
                f"  summary[{key}]: ok={n_ok}/{len(recs)} "
                f"pass={n_pass} mean={summaries[key]['mean_score']}"
            )
    else:
        modes: list[tuple[str, str | None]] = []
        if mode == "single_worker":
            wid = worker_id or settings.workers[0].id
            modes.append(("single_worker", wid))
        else:
            modes.append((mode, worker_id))

        for m, wid in modes:
            key = f"single_worker:{wid}" if m == "single_worker" else m
            print(f"\n######## mode={key} ########")
            if m == "single_worker" and wid:
                print(f"  model={model_map.get(wid, '?')}")
            recs: list[dict[str, Any]] = []
            n_ok = 0
            n_pass = 0
            t0 = time.perf_counter()
            time.sleep(pause)
            for task in tasks:
                rec = _run_one_live(
                    task,
                    mode=m,
                    worker_id=wid,
                    settings=settings,
                    timeout_s=timeout_s,
                )
                if rec["ok"]:
                    n_ok += 1
                if (rec.get("answer_score") or {}).get("passed"):
                    n_pass += 1
                _print_rec(key, rec)
                recs.append(rec)
                time.sleep(pause)
            total_ms = (time.perf_counter() - t0) * 1000.0
            per_mode[key] = recs
            summaries[key] = {
                "mode": key,
                "n_tasks": len(tasks),
                "ok_count": n_ok,
                "answer_pass": n_pass,
                "answer_pass_rate": round(n_pass / len(tasks), 3) if tasks else 0.0,
                "mean_score": round(
                    sum(_numeric_score(r) for r in recs) / len(recs), 3
                )
                if recs
                else 0.0,
                "total_latency_ms": round(total_ms, 2),
                "models_used": (
                    [model_map.get(wid or "", wid or "")]
                    if m == "single_worker"
                    else sorted(set(model_map.values()))
                ),
            }
            print(
                f"  summary: ok={n_ok}/{len(tasks)} "
                f"answer_pass={n_pass} rate={summaries[key]['answer_pass_rate']*100:.1f}% "
                f"mean_score={summaries[key]['mean_score']}"
            )

    payload: dict[str, Any] = {
        "kind": "live" if mode != "all" else "live_all",
        "seed": {"n_tasks": len(tasks), "task_ids": [t.id for t in tasks]},
        "worker_tags": tags,
        "worker_ids": worker_ids,
        "models": model_map,
        "timeout_s": timeout_s,
        "workers_path": str(workers_path or _DEFAULT_WORKERS_YAML),
        "summaries": summaries,
        "results_by_mode": per_mode,
    }

    if mode == "all":
        rows = build_comparison_table(tasks, per_mode, worker_ids)
        # SHIP uses ABSOLUTE verifier scores only (no pairwise +1 margin injection).
        # Pairwise may still be logged for audit when env NORTHSTAR_PAIRWISE_AUDIT=1.
        if os.environ.get("NORTHSTAR_PAIRWISE_AUDIT", "").strip().lower() in (
            "1",
            "true",
            "yes",
        ):
            audit_rows = apply_pairwise_ceiling_breaks(
                [dict(r) for r in rows], per_mode, tasks, worker_ids
            )
            payload["pairwise_audit"] = audit_rows
        metrics = comparison_metrics(rows)
        md = print_comparison_markdown(rows, worker_ids, metrics)
        payload["comparison"] = {
            "rows": rows,
            "metrics": metrics,
            "markdown": md,
        }
        payload["summary"] = metrics
        print("\n--- mode=all north-star (ABSOLUTE scores only) ---")
        print(
            f"  conductor_beats_every_worker="
            f"{metrics['conductor_beats_every_worker_rate']*100:.1f}% "
            f"conductor_beats_max_worker="
            f"{metrics['conductor_beats_max_worker_rate']*100:.1f}% "
            f"mean_delta={metrics.get('mean_delta', 0):.3f} "
            f"SHIP={metrics.get('SHIP', 'NO')} "
            f"conductor_wins={metrics['conductor_wins_count']}/{metrics['n_tasks']}"
        )
        payload["SHIP"] = metrics.get("SHIP", "NO")
        payload["northstar"] = {
            "win_rate": metrics.get("win_rate_vs_max_solo"),
            "mean_delta": metrics.get("mean_delta"),
            "SHIP": metrics.get("SHIP"),
            "strict_beat": True,
            "score_scale": "0-10_absolute_multipart",
            "pairwise_ceiling_break": False,
            "synthetic_margin": False,
        }

    return payload


# ---------------------------------------------------------------------------
# Persist
# ---------------------------------------------------------------------------


def write_results(payload: dict[str, Any], out_path: Path | str | None = None) -> Path:
    """Write results JSON under eval_results/ (or explicit path)."""
    if out_path is None:
        _DEFAULT_RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        kind = payload.get("kind") or "eval"
        out_path = _DEFAULT_RESULTS_DIR / f"{kind}_{stamp}.json"
    else:
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)

    envelope = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "harness": "routism_orch.eval_conductor",
        **payload,
    }
    out_path.write_text(json.dumps(envelope, indent=2, default=str) + "\n", encoding="utf-8")
    print(f"\nWrote results → {out_path}")
    return out_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m routism_orch.eval_conductor",
        description=(
            "North-star eval: Routism(pool) vs single workers. "
            "MVP: --dry-run validates seed + heuristic_plan/structural_repair. "
            "Live: --mode all compares each worker, parallel, and conductor."
        ),
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="No live APIs: validate seed and score plan structure only",
    )
    p.add_argument(
        "--mode",
        choices=_MODES,
        default=None,
        help="Live mode: single_worker | parallel | conductor | all",
    )
    p.add_argument(
        "--worker-id",
        default=None,
        help="Worker id for --mode single_worker",
    )
    p.add_argument(
        "--seed",
        type=Path,
        default=_DEFAULT_SEED,
        help=f"Path to seed JSON (default: {_DEFAULT_SEED})",
    )
    p.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Results JSON path (default: eval_results/<kind>_<timestamp>.json)",
    )
    p.add_argument(
        "--validate-only",
        action="store_true",
        help="Only validate seed structure and exit",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=None,
        metavar="N",
        help="Only evaluate the first N tasks from the seed",
    )
    p.add_argument(
        "--workers",
        type=Path,
        default=None,
        help=f"Path to routism.yaml pool config (default: {_DEFAULT_WORKERS_YAML})",
    )
    p.add_argument(
        "--timeout",
        type=float,
        default=None,
        metavar="SEC",
        help="Per-call wall-clock timeout in seconds (live modes)",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        seed_summary = validate_seed(args.seed)
    except (OSError, ValueError, json.JSONDecodeError) as e:
        print(f"SEED ERROR: {e}", file=sys.stderr)
        return 2

    print("Seed OK:", json.dumps(seed_summary, indent=2))
    if args.validate_only:
        return 0

    tasks = load_seed(args.seed)
    if args.limit is not None:
        if args.limit < 0:
            print("ERROR: --limit must be >= 0", file=sys.stderr)
            return 2
        tasks = tasks[: args.limit]
        print(f"Limited to first {len(tasks)} task(s)")

    # MVP default: offline plan-structure eval when --dry-run or no --mode.
    if args.dry_run or args.mode is None:
        payload = run_dry(tasks)
        write_results(payload, args.out)
        rate = payload["summary"]["plan_pass_rate"]
        # Soft gate: majority of multi-step plans should pass structure checks
        return 0 if rate >= 0.5 else 1

    # Live modes need workers / engine APIs.
    try:
        payload = run_live(
            tasks,
            mode=args.mode,
            worker_id=args.worker_id,
            workers_path=args.workers,
            timeout_s=args.timeout,
        )
    except Exception as e:  # noqa: BLE001
        print(f"LIVE ERROR: {e}", file=sys.stderr)
        print(
            "Hint: use --dry-run for offline plan-structure eval "
            "(python -m routism_orch.eval_conductor --dry-run)",
            file=sys.stderr,
        )
        return 3

    write_results(payload, args.out)
    # Soft: all modes should have answer_pass_rate defined; exit 0 if any mode ran
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
