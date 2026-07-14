"""Recovery-before-merge: re-run failed DAG nodes with alternate workers.

Product path only — fills holes before sectioned stitch so multi-part
deliverables (especially unit tests) are not left NOT PRODUCED.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Protocol


class _HasResult(Protocol):
    id: str
    prompt: str
    result: str | None
    error: str | None
    assigned_worker: str | None
    selected_worker_id: str | None


@dataclass
class RecoveryResult:
    """Outcome of one recovery attempt."""

    subtask_id: str
    worker_id: str
    answer: str | None
    error: str | None
    elapsed_ms: float = 0.0
    recovered: bool = False


@dataclass
class RecoveryPlanView:
    """Minimal plan view for recovery (avoids circular imports in tests)."""

    subtasks: list[Any] = field(default_factory=list)


def build_prior_context(subtasks: list[Any], *, per_step_cap: int = 2500, total_cap: int = 7000) -> str:
    bits: list[str] = []
    for st in subtasks:
        if getattr(st, "result", None) and not getattr(st, "error", None):
            bits.append(
                f"### Completed {st.id}\n{(st.result or '')[:per_step_cap]}"
            )
    return "\n\n".join(bits)[:total_cap]


def build_recovery_prompt(query: str, st: Any, prior_ctx: str) -> str:
    """Strong recovery prompt: demand concrete artifact for THIS step only."""
    role_hint = ""
    pl = (getattr(st, "prompt", None) or "").lower()
    if "test" in pl or "unit" in pl:
        role_hint = (
            "\nThis step requires REAL unit tests with assert/test_ functions "
            "and concrete inputs (valid + invalid cases). Prose-only is failure.\n"
        )
    elif "implement" in pl or "handler" in pl or "python" in pl:
        role_hint = (
            "\nThis step requires REAL runnable code (def / ```python). "
            "Prose-only is failure.\n"
        )
    return (
        f"RECOVERY TASK (prior specialist step failed — produce this deliverable NOW).\n"
        f"USER GOAL:\n{query}\n\n"
        f"YOUR STEP ({st.id}):\n{st.prompt}\n"
        f"{role_hint}\n"
        f"PRIOR SUCCESSFUL STEPS (use as context; do not redo them):\n"
        f"{prior_ctx or '(none)'}\n\n"
        "Output the concrete artifact for THIS step only "
        "(code/tests/notes as requested). Start with a markdown heading. No preamble."
    )


def order_recovery_workers(
    *,
    pool_ids: list[str],
    failed_worker_ids: set[str],
    success_worker_ids: list[str],
    prefer_code_ids: list[str] | None = None,
    step_is_test_or_code: bool = False,
) -> list[str]:
    """Pick alternate workers: prefer successes, then code-strong, never failed first."""
    prefer_code_ids = prefer_code_ids or []
    exclude = set(failed_worker_ids)
    ordered: list[str] = []

    def _add(wid: str) -> None:
        if wid and wid not in exclude and wid not in ordered and wid in pool_ids:
            ordered.append(wid)

    if step_is_test_or_code:
        for wid in prefer_code_ids:
            _add(wid)
    for wid in success_worker_ids:
        _add(wid)
    for wid in prefer_code_ids:
        _add(wid)
    for wid in pool_ids:
        _add(wid)
    # last resort: include failed if nothing else
    if not ordered:
        ordered = list(pool_ids)
    return ordered


def is_test_or_code_step(st: Any) -> bool:
    """Detect test/implement steps without matching the overall-goal dump.

    Work orders embed the full user goal (which often mentions tests/python).
    Use content_role / node_role / Work order role line / step assignment only.
    """
    role = (
        str(getattr(st, "content_role", None) or "")
        + " "
        + str(getattr(st, "node_role", None) or "")
    ).lower()
    if any(k in role for k in ("test", "implement", "code", "handler")):
        return True
    prompt = getattr(st, "prompt", None) or ""
    # Prefer the work-order role line / first ~12 lines (not full goal dump)
    head_lines: list[str] = []
    for line in prompt.splitlines()[:14]:
        low = line.lower().strip()
        if low.startswith("### overall") or low.startswith("user goal"):
            break
        head_lines.append(low)
    head = "\n".join(head_lines)
    # role=test/produce or "Step N · role=implement"
    if re.search(r"role\s*=\s*(test|implement|code)\b", head):
        return True
    if re.search(r"\b(unit test|write tests|implement|fastapi handler)\b", head):
        return True
    return False


def _step_head(st: Any) -> str:
    role = (
        str(getattr(st, "content_role", None) or "")
        + " "
        + str(getattr(st, "node_role", None) or "")
    ).lower()
    prompt = getattr(st, "prompt", None) or ""
    head_lines: list[str] = [role]
    for line in prompt.splitlines()[:14]:
        low = line.lower().strip()
        if low.startswith("### overall") or low.startswith("user goal"):
            break
        head_lines.append(low)
    return "\n".join(head_lines)


def answer_has_required_artifacts(st: Any, answer: str | None) -> bool:
    """Return False when a code/test step answer lacks concrete artifacts."""
    ans = (answer or "").strip()
    if not ans:
        return False
    if not is_test_or_code_step(st):
        return len(ans) >= 40
    head = _step_head(st)
    needs_test = bool(re.search(r"\b(test|unit)\b", head))
    needs_code = bool(re.search(r"\b(implement|handler|fastapi|code)\b", head))
    if needs_test and not any(x in ans for x in ("assert", "test_", "pytest", "unittest")):
        return False
    if needs_code and "def " not in ans and "```" not in ans:
        return False
    # Thin test bodies are not acceptable; code with real def can be short
    if needs_test and len(ans) < 100:
        return False
    if needs_code and "def " not in ans and len(ans) < 100:
        return False
    return True


def needs_recovery(st: Any) -> bool:
    """True if subtask failed hard OR produced artifact-thin code/test output."""
    if not (getattr(st, "result", None) and not getattr(st, "error", None)):
        return True
    return not answer_has_required_artifacts(st, getattr(st, "result", None))


async def recovery_fill_failed_nodes(
    *,
    query: str,
    subtasks: list[Any],
    pool_ids: list[str],
    call_worker: Callable[[str, str], Awaitable[tuple[str | None, str | None, float]]],
    prefer_code_ids: list[str] | None = None,
    max_recoveries: int = 4,
) -> list[RecoveryResult]:
    """Re-attempt failed or artifact-thin subtasks with alternate workers.

    ``call_worker(worker_id, prompt) -> (answer, error, elapsed_ms)``.
    Mutates subtask.result/error/selected_worker_id on success.
    Returns list of RecoveryResult (including failures).
    """
    prefer_code_ids = prefer_code_ids or [
        w for w in ("kilo", "groq", "nvidia-nim", "opencode") if w in pool_ids
    ]
    failed = [st for st in subtasks if needs_recovery(st)]
    if not failed:
        return []

    prior_ctx = build_prior_context(subtasks)
    success_wids = [
        getattr(st, "selected_worker_id", None) or getattr(st, "assigned_worker", None)
        for st in subtasks
        if getattr(st, "result", None) and not getattr(st, "error", None)
    ]
    success_wids = [w for w in success_wids if w]

    out: list[RecoveryResult] = []
    for st in failed[:max_recoveries]:
        ban = {
            getattr(st, "assigned_worker", None),
            getattr(st, "selected_worker_id", None),
        } - {None}
        ordered = order_recovery_workers(
            pool_ids=pool_ids,
            failed_worker_ids=ban,  # type: ignore[arg-type]
            success_worker_ids=success_wids,
            prefer_code_ids=prefer_code_ids,
            step_is_test_or_code=is_test_or_code_step(st),
        )
        prompt = build_recovery_prompt(query, st, prior_ctx)
        recovered = False
        last_err: str | None = None
        last_wid = ordered[0] if ordered else ""
        for wid in ordered[:3]:  # try up to 3 alternates
            last_wid = wid
            try:
                answer, err, elapsed = await call_worker(wid, prompt)
            except Exception as e:  # noqa: BLE001
                answer, err, elapsed = None, f"{type(e).__name__}: {e}", 0.0
            if answer and not err and answer_has_required_artifacts(st, answer):
                st.result = answer
                st.error = None
                st.selected_worker_id = wid
                st.assigned_worker = wid
                out.append(
                    RecoveryResult(
                        subtask_id=st.id,
                        worker_id=wid,
                        answer=answer,
                        error=None,
                        elapsed_ms=elapsed,
                        recovered=True,
                    )
                )
                recovered = True
                # refresh context for subsequent recoveries
                prior_ctx = build_prior_context(subtasks)
                success_wids.append(wid)
                break
            last_err = err or "empty/thin recovery answer"
        if not recovered:
            out.append(
                RecoveryResult(
                    subtask_id=st.id,
                    worker_id=last_wid,
                    answer=None,
                    error=last_err,
                    recovered=False,
                )
            )
    return out
