"""P1.A — gated verifier (ACCEPT / REJECT) + repair loop.

The verifier is a callable that inspects a worker's output and decides whether
to ACCEPT it or REJECT it (with a reason). On REJECT the executor retries the
step (repair) and, if repairs are exhausted on the preferred worker, re-routes
to the next-best worker in the pool. Mirrors Fugu Ultra's Verifier role
(arch §4/§6) — the "repair loop" the v0 eval said was missing.

Deterministic stubs let the gate run without a second (verifier) model.
"""
from __future__ import annotations

from typing import Callable, Dict, Tuple

from .config import Worker
from . import worker as worker_mod

# (accepted: bool, reason: str)
VerifierFn = Callable[[str, str, Dict[int, str]], Tuple[bool, str]]


def always_accept(target: str, subtask: str, ctx: Dict[int, str]) -> Tuple[bool, str]:
    return True, "ok"


def always_reject(target: str, subtask: str, ctx: Dict[int, str]) -> Tuple[bool, str]:
    return False, "always reject"


def reject_once_then_accept(times: int = 1) -> VerifierFn:
    """REJECT the first `times` calls, then ACCEPT. For gate tests."""
    state = {"n": 0}

    def fn(target: str, subtask: str, ctx: Dict[int, str]) -> Tuple[bool, str]:
        if state["n"] < times:
            state["n"] += 1
            return False, f"rejected attempt {state['n']}"
        return True, "accepted after repairs"

    return fn


def raise_worker_error(target: str, subtask: str, ctx: Dict[int, str]) -> Tuple[bool, str]:
    """Stub that simulates the verifier itself failing (e.g. its worker 5xx)."""
    raise worker_mod.WorkerError(f"verifier worker failed on subtask {subtask!r}")


_VERIFY_SYSTEM = (
    "You are a strict verifier for one step of an LLM orchestration.\n"
    "Given the subtask and the worker's output, decide if the output is a "
    "correct, complete, and consistent answer to the subtask.\n"
    "Respond with EXACTLY one line: either 'ACCEPT' or 'REJECT: <short reason>'.\n"
    "Do not write any other text."
)


def make_llm_verifier(worker: Worker) -> VerifierFn:
    """Build a real LLM-backed verifier that reuses one pool worker.

    Used when settings.verifier_worker_id is configured. If the worker call
    raises WorkerError it propagates (the API layer catches it).
    """

    def verify(
        target: str, subtask: str, ctx: Dict[int, str]
    ) -> Tuple[bool, str]:
        context_block = ""
        if ctx:
            context_block = "\nPrior context:\n" + "\n".join(
                f"[step {k}] {v[:500]}" for k, v in ctx.items()
            )
        messages = [
            {"role": "system", "content": _VERIFY_SYSTEM},
            {
                "role": "user",
                "content": (
                    f"Subtask: {subtask}\n{context_block}\n\n"
                    f"Worker output:\n{target}\n\n"
                    "Verdict (ACCEPT or REJECT: reason):"
                ),
            },
        ]
        raw = worker_mod.complete(worker, messages, max_tokens=128)
        line = raw.strip().splitlines()[0] if raw.strip() else ""
        up = line.upper()
        if up.startswith("ACCEPT"):
            return True, line
        if up.startswith("REJECT"):
            return False, line[len("REJECT") :].strip(": ").strip()
        # Undecided -> FAIL CLOSED. A verifier that can't decide must REJECT so
        # the executor's repair/re-route loop gets a chance to fix the step.
        # Accepting on undecided (the old behavior) let broken outputs through
        # and defeated the whole gate — the live Phase-2 eval caught a garbage
        # step being wrongly ACCEPTED this way.
        return False, f"undecided ({line!r}) -> reject (fail-closed)"

    return verify
