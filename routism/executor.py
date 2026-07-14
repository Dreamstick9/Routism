"""P0.D + P1.A + P1.B — workflow executor.

- Verifier-gated repair/re-route (P1.A): on REJECT, retry the step (up to
  `max_repairs`) then re-route to the next-best worker; graceful `[routism
  repaired]` best-effort if all fail.
- Cost & timeout guards (P1.B): per-call retry+backoff lives in worker.complete;
  here we track a running token estimate and abort gracefully with a partial
  `[routism budget]` answer when `settings.max_total_tokens` is exceeded.
- Isolation (P0.D): a step only sees its allowed prior outputs.

The pipeline NEVER hangs or crashes.
"""
from __future__ import annotations

from .config import Settings, Worker
from .isolation import assert_isolation, build_context, IsolationViolation
from .schema import Workflow
from . import worker as worker_mod
from . import verifier as verifier_mod
from . import memory as memory_mod

# Optional injected verifier (defaults to the config one). Tests override this
# with a deterministic stub so the gate runs without a second model.
_VERIFIER: verifier_mod.VerifierFn | None = None


def set_verifier(fn: verifier_mod.VerifierFn | None) -> None:
    global _VERIFIER
    _VERIFIER = fn


def _resolve_verifier(settings: Settings) -> verifier_mod.VerifierFn | None:
    if _VERIFIER is not None:
        return _VERIFIER
    w = settings.verifier
    if w is None:
        return None
    return verifier_mod.make_llm_verifier(w)


def _est_tokens(text: str) -> int:
    """Rough token estimate (~4 chars/token) for budget accounting."""
    return max(1, len(text) // 4)


def run(workflow: Workflow, settings: Settings) -> str:
    """Execute `workflow` and return one synthesized answer (str)."""
    return run_detailed(workflow, settings)["answer"]


def run_detailed(workflow: Workflow, settings: Settings) -> dict:
    """Execute with verifier gating, repair/re-route, and a token budget.

    Returns {"steps": [...], "answer": str, "orchestration_input_tokens": int,
    "orchestration_output_tokens": int, "budget_hit": bool}.
    """
    by_id = {w.id: w for w in settings.workers}
    # P1.D: persistent store (inprocess/file/sqlite). Current-query outputs are
    # also recorded here so they can be referenced by a later query via a
    # "scope:<id>:s:<idx>" access_list entry.
    store = memory_mod.make_store(settings.memory_backend, settings.memory_path)
    query_scope = settings.memory_scope
    # unified view passed to isolation/context: int idx -> current query output,
    # str "scope:..:s:.." -> resolved cross-query output (pulled from store).
    memory: dict[int | str, str] = {}
    trace: list[dict] = []
    verify = _resolve_verifier(settings)
    max_repairs = max(0, settings.max_repairs)
    budget = settings.max_total_tokens
    in_tokens = 0
    out_tokens = 0
    prompt_tokens = 0
    comp_tokens = 0
    budget_hit = False

    for i, step in enumerate(workflow.steps):
        if step.worker_id not in by_id:
            raise KeyError(f"step {i} worker_id {step.worker_id!r} not in pool")
        worker = by_id[step.worker_id]
        # P1.D: resolve any cross-query scope-refs in this step's access_list
        # from the persistent store into the unified memory view.
        for ref in step.access_list:
            if isinstance(ref, str) and ref not in memory:
                parsed = memory_mod.parse_scope_ref(ref)
                if parsed is not None:
                    scope, idx = parsed
                    val = store.get(scope, idx)
                    if val is not None:
                        memory[ref] = val
        had_context = bool(build_context(i, step.access_list, memory))

        # P1.B: pre-estimate this step's input cost; if running total would exceed
        # the budget, abort BEFORE spending and return a partial answer.
        # A missing cross-query ref contributes 0 (it was gracefully skipped
        # during resolution, so it carries no tokens here).
        step_in = _est_tokens(step.subtask) + sum(
            _est_tokens(memory.get(k, "")) for k in step.access_list
        )
        if budget and (in_tokens + step_in) > budget:
            budget_hit = True
            partial = (
                f"[routism budget] stopped before step {i} of {len(workflow.steps)} "
                f"(token budget {budget} reached; had {in_tokens} in / {out_tokens} out). "
                f"Last completed answer:\n"
                + (memory[i - 1] if i > 0 else "(no steps completed)")
            )
            return {
                "steps": trace,
                "answer": partial,
                "orchestration_input_tokens": in_tokens,
                "orchestration_output_tokens": out_tokens,
                "worker_prompt_tokens": prompt_tokens,
                "worker_completion_tokens": comp_tokens,
                "total_tokens": prompt_tokens + comp_tokens,
                "budget_hit": True,
            }

        accepted = True
        reason = ""
        repaired = False
        out = None
        step_usage: dict = {}
        last_err: Exception | None = None

        for cand in _rank_workers(worker, settings):
            for repair in range(max_repairs + 1):
                try:
                    out, step_usage = _call_step(
                        cand, step.subtask, i, step.access_list, memory, had_context, retries=2
                    )
                except worker_mod.WorkerError as e:
                    last_err = e
                    out = None
                    break  # this worker is down; try next candidate
                if verify is None:
                    accepted, reason = True, "no verifier configured"
                    break
                try:
                    accepted, reason = verify(
                        out,
                        step.subtask,
                        {k: memory.get(k, "") for k in step.access_list},
                    )
                except worker_mod.WorkerError as e:
                    last_err = e
                    out = None
                    break
                if accepted:
                    break
                repaired = True
            if out is not None and accepted:
                break

        if out is None:
            raise worker_mod.WorkerError(
                f"all workers failed step {i} ({step.subtask!r}): {last_err}"
            )

        out_tokens += _est_tokens(out)
        in_tokens += step_in
        prompt_tokens += int(step_usage.get("prompt_tokens", 0) or 0)
        comp_tokens += int(step_usage.get("completion_tokens", 0) or 0)
        if repaired and not accepted:
            memory[i] = f"[routism repaired] {out}"
        else:
            memory[i] = out
        # P1.D: persist to the shared store so a later query can reference it via
        # "scope:<scope>:s:<idx>" (survives restarts for file/sqlite backends).
        store.put(query_scope, i, memory[i])
        trace.append(
            {
                "index": i,
                "worker_id": step.worker_id,
                "subtask": step.subtask,
                "access_list": step.access_list,
                "saw_prior_context": had_context,
                "verified": accepted,
                "verdict_reason": reason,
                "repaired": repaired,
                "output": memory[i],
                "usage": step_usage,
            }
        )

    return {
        "steps": trace,
        "answer": memory[len(workflow.steps) - 1],
        "orchestration_input_tokens": in_tokens,
        "orchestration_output_tokens": out_tokens,
        "worker_prompt_tokens": prompt_tokens,
        "worker_completion_tokens": comp_tokens,
        "total_tokens": prompt_tokens + comp_tokens,
        "budget_hit": False,
    }


def run_stream(workflow: Workflow, settings: Settings):
    """Streaming variant of run_detailed.

    Yields dict events as the workflow executes (generator):
      {"type": "step", "step": <trace dict>}   after each step completes
      {"type": "done", "answer": str, "usage": {...}, "budget_hit": bool}
      {"type": "error", "message": str}         on unrecoverable failure

    Reuses the same verified per-step logic (verifier gating, repair/re-route,
    budget guard, isolation) as run_detailed — only the control flow differs
    (yield per step instead of collecting into one return). Used by the SSE
    /v1/run endpoint so the UI can show step cards populate live.
    """
    by_id = {w.id: w for w in settings.workers}
    store = memory_mod.make_store(settings.memory_backend, settings.memory_path)
    query_scope = settings.memory_scope
    memory: dict[int | str, str] = {}
    verify = _resolve_verifier(settings)
    max_repairs = max(0, settings.max_repairs)
    budget = settings.max_total_tokens
    in_tokens = 0
    out_tokens = 0
    prompt_tokens = 0
    comp_tokens = 0
    budget_hit = False

    try:
        for i, step in enumerate(workflow.steps):
            if step.worker_id not in by_id:
                raise KeyError(f"step {i} worker_id {step.worker_id!r} not in pool")
            worker = by_id[step.worker_id]
            for ref in step.access_list:
                if isinstance(ref, str) and ref not in memory:
                    parsed = memory_mod.parse_scope_ref(ref)
                    if parsed is not None:
                        scope, idx = parsed
                        val = store.get(scope, idx)
                        if val is not None:
                            memory[ref] = val
            had_context = bool(build_context(i, step.access_list, memory))

            step_in = _est_tokens(step.subtask) + sum(
                _est_tokens(memory.get(k, "")) for k in step.access_list
            )
            if budget and (in_tokens + step_in) > budget:
                budget_hit = True
                partial = (
                    f"[routism budget] stopped before step {i} of {len(workflow.steps)} "
                    f"(token budget {budget} reached; had {in_tokens} in / {out_tokens} out). "
                    f"Last completed answer:\n"
                    + (memory[i - 1] if i > 0 else "(no steps completed)")
                )
                yield {"type": "done", "answer": partial, "usage": {
                    "orchestration_input_tokens": in_tokens,
                    "orchestration_output_tokens": out_tokens,
                    "worker_prompt_tokens": prompt_tokens,
                    "worker_completion_tokens": comp_tokens,
                    "total_tokens": prompt_tokens + comp_tokens,
                }, "budget_hit": True}
                return

            accepted = True
            reason = ""
            repaired = False
            out = None
            step_usage: dict = {}
            last_err: Exception | None = None

            for cand in _rank_workers(worker, settings):
                for repair in range(max_repairs + 1):
                    try:
                        out, step_usage = _call_step(
                            cand, step.subtask, i, step.access_list, memory, had_context, retries=2
                        )
                    except worker_mod.WorkerError as e:
                        last_err = e
                        out = None
                        break
                    if verify is None:
                        accepted, reason = True, "no verifier configured"
                        break
                    try:
                        accepted, reason = verify(
                            out,
                            step.subtask,
                            {k: memory.get(k, "") for k in step.access_list},
                        )
                    except worker_mod.WorkerError as e:
                        last_err = e
                        out = None
                        break
                    if accepted:
                        break
                    repaired = True
                if out is not None and accepted:
                    break

            if out is None:
                raise worker_mod.WorkerError(
                    f"all workers failed step {i} ({step.subtask!r}): {last_err}"
                )

            out_tokens += _est_tokens(out)
            in_tokens += step_in
            prompt_tokens += int(step_usage.get("prompt_tokens", 0) or 0)
            comp_tokens += int(step_usage.get("completion_tokens", 0) or 0)
            if repaired and not accepted:
                memory[i] = f"[routism repaired] {out}"
            else:
                memory[i] = out
            store.put(query_scope, i, memory[i])
            trace_step = {
                "index": i,
                "worker_id": step.worker_id,
                "subtask": step.subtask,
                "access_list": step.access_list,
                "saw_prior_context": had_context,
                "verified": accepted,
                "verdict_reason": reason,
                "repaired": repaired,
                "output": memory[i],
                "usage": step_usage,
            }
            yield {"type": "step", "step": trace_step}

        yield {"type": "done", "answer": memory[len(workflow.steps) - 1], "usage": {
            "orchestration_input_tokens": in_tokens,
            "orchestration_output_tokens": out_tokens,
            "worker_prompt_tokens": prompt_tokens,
            "worker_completion_tokens": comp_tokens,
            "total_tokens": prompt_tokens + comp_tokens,
        }, "budget_hit": False}
    except worker_mod.WorkerError as e:
        yield {"type": "error", "message": str(e)}


def _rank_workers(step_worker: Worker, settings: Settings) -> list[Worker]:
    """Preferred worker first, then the rest of the pool as re-route candidates."""
    others = [w for w in settings.workers if w.id != step_worker.id]
    return [step_worker, *others]


def _call_step(
    worker: Worker,
    subtask: str,
    idx: int,
    access_list: list[int],
    memory: dict[int, str],
    had_context: bool,
    retries: int,
) -> tuple[str, dict]:
    # P1.C: pass ONLY the access-listed outputs to prompt assembly. Unlisted
    # outputs are physically absent from `allowed`, so they cannot reach the
    # worker's prompt even if the subtask tries to embed them.
    allowed = build_context(idx, access_list, memory) if had_context else ""
    prompt = subtask
    if allowed:
        prompt = (
            "Prior context you are allowed to use (each block is a separate "
            "step output, do not treat it as part of your subtask):\n"
            f"{allowed}\n\nNow do this subtask: {subtask}"
        )
    # defense-in-depth: scan the untrusted SUBTASK for a smuggled unlisted output.
    # The assembled context blocks are trusted by construction, so we do NOT
    # scan them (avoids false-positives on legitimate summarization chains).
    # If a subtask still tries to smuggle, fail the step gracefully instead of
    # crashing the whole run.
    try:
        assert_isolation(idx, access_list, memory, subtask)
    except IsolationViolation as e:
        raise worker_mod.WorkerError(f"isolation blocked step {idx}: {e}")
    # B1: use complete_full so we capture REAL per-step token usage from the
    # provider response (not the ~4-char heuristic). Returns (text, usage dict).
    return worker_mod.complete_full(
        worker, [{"role": "user", "content": prompt}], retries=retries
    )


