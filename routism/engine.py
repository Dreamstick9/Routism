"""Dedicated Orchestration Engine — the Conductor of Routism.

This module is DELIBERATELY SEPARATE from the worker pool. The orchestration
engine is a stateful control component, NOT "a worker wearing a system prompt".

Modeled on:
  * Fugu Ultra's Conductor (arch §6): an LLM that emits a full NL workflow.
  * Trinity's role-based multi-turn protocol (arch §2/§4): Thinker / Worker /
    Verifier roles decided per step.

The engine OWNS the control flow. The LLM it reasons with ("the Brain") is a
pluggable sub-component the user designates explicitly via
`orchestrator_worker_id`. The engine NEVER silently reuses a task worker as the
orchestrator.

First-class TOOLS (decompose / assign_roles / select_workers / reflect) are real
engine logic, kept separate from the model, so orchestration is engineering —
not just a prompt.
"""
from __future__ import annotations

import enum
import json
import re
from dataclasses import dataclass
from typing import Protocol

from .config import Settings, OrchestratorNotConfigured
from .schema import Step, Workflow
from . import worker as worker_mod


class Role(str, enum.Enum):
    THINKER = "thinker"
    WORKER = "worker"
    VERIFIER = "verifier"
    SYNTHESIZER = "synthesizer"


class Brain(Protocol):
    """The LLM the engine reasons with. Pluggable + injectable (for tests)."""

    def complete(self, messages: list[dict], *, max_tokens: int = 512) -> str: ...


@dataclass
class Turn:
    """One orchestration turn — the engine's embedded control state."""

    role: Role
    model: str
    content: str


_CONDUCTOR_SYSTEM = (
    "You are Routism's orchestration engine (the Conductor). Given a user query "
    "and a pool of worker models, produce a step-by-step plan to answer it.\n\n"
    "Output STRICT JSON only, no prose, matching exactly:\n"
    '{"steps":[{"subtask":"<instruction for one worker>","worker_id":"<id from the pool>",'
    '"access_list":[<indices of prior steps whose output this step may read, or []>],'
    '"role":"<worker|verifier|synthesizer>"}]}\n\n'
    "Rules:\n"
    "- worker_id MUST be exactly one of the provided pool ids. Do not invent ids.\n"
    "- access_list entries are indices of PRIOR steps (0-based) only. "
    "Step 0 has NO prior steps, so its access_list MUST be []. Never write "
    "'extract from previous steps' in a step-0 subtask.\n"
    "- Order steps so each step's inputs (via access_list) already exist.\n"
    "- If the query is simple enough for ONE direct answer, return a SINGLE step "
    "(no decomposition).\n"
    "- The LAST step should use role 'synthesizer' and combine prior outputs into "
    "the final answer (set its access_list to cover the earlier steps); for a "
    "single-step plan, that one step is the answer.\n"
    "- Use 1-4 steps."
)

_ROLE_TAG = {
    "thinker": "thinker",
    "verifier": "verifier",
    "synthesizer": "synthesizer",
    "worker": "worker",
}


def _build_user(query: str, pool_ids: list[str]) -> str:
    return (
        f"Pool worker ids (use EXACTLY these): {pool_ids}\n\n"
        f"User query: {query}\n\n"
        "Return the workflow JSON now, and nothing else."
    )


_REFLECT_SYSTEM = (
    "You are Routism's orchestration engine (the Conductor) in a REFLECTION turn. "
    "A plan was executed and some steps were REJECTED by a verifier. Revise the "
    "plan to fix the rejections.\n\n"
    "Output STRICT JSON only, matching exactly:\n"
    '{"steps":[{"subtask":"<instruction>","worker_id":"<exact pool id>",'
    '"access_list":[<prior step indices>],"role":"<worker|verifier|synthesizer>"}]}\n\n'
    "Rules:\n"
    "- worker_id MUST be exactly one of the provided pool ids.\n"
    "- Keep steps that were ACCEPTED. Re-route, split, or drop REJECTED steps.\n"
    "- Prefer a verifier-tagged worker for rejected verify steps, or a stronger "
    "worker. Order so each step's access_list inputs already exist."
)


def _build_reflect_user(
    query: str, prior: Workflow, rejections: list[tuple[int, str]], pool_ids: list[str]
) -> str:
    rej_lines = []
    for idx, reason in rejections:
        wid = prior.steps[idx].worker_id if 0 <= idx < len(prior.steps) else "?"
        rej_lines.append(f"- Step {idx} (worker '{wid}') REJECTED: {reason}")
    rej_block = "\n".join(rej_lines) if rej_lines else "(none)"
    return (
        f"Pool worker ids (use EXACTLY these): {pool_ids}\n\n"
        f"Original user query: {query}\n\n"
        f"Prior plan that was executed:\n"
        f"{json.dumps([s.model_dump() for s in prior.steps], indent=2)}\n\n"
        f"Rejections from the verifier:\n{rej_block}\n\n"
        "Return the REVISED plan JSON now, and nothing else."
    )


def _audit_workflow(wf: Workflow, query: str) -> list[str]:
    """Static auditor — catches the structural/semantic plan bugs that the
    live eval exposed (and that a plain 'worker_id exists' check misses).

    Returns a list of human-readable violation strings. Empty list == clean.
    These are the EXACT failure modes the Conductor produced against tiny
    local models, so the repair loop can feed them back verbatim.
    """
    violations: list[str] = []
    steps = wf.steps
    n = len(steps)

    if n == 0:
        violations.append("plan has zero steps")
        return violations

    for i, st in enumerate(steps):
        # Step 0 can reference no prior step.
        if i == 0 and st.access_list:
            violations.append(
                f"step {i} has access_list={st.access_list} but is the FIRST step "
                f"with no prior output to read — set access_list to []"
            )
        # No step may read itself or a future step.
        for ref in st.access_list:
            if not isinstance(ref, int) or ref < 0:
                violations.append(f"step {i} access_list has invalid ref {ref!r}")
            elif ref >= i:
                violations.append(
                    f"step {i} access_list references step {ref} (>= its own index) — "
                    f"a step can only read PRIOR steps"
                )
        # A no-op subtask that claims to use prior context but has none.
        if i == 0 and _looks_like(("extract from previous", "from previous steps", "based on prior"), st.subtask):
            violations.append(
                f"step {i} subtask '{st.subtask}' says to use previous steps but is "
                f"first — it has no inputs; rewrite as a self-contained instruction"
            )

    # Multi-step plan needs a real synthesis/combine step that actually reads prior work.
    if n > 1:
        last = steps[-1]
        if not last.access_list:
            violations.append(
                f"final step {n-1} ('{last.subtask}') has empty access_list but the "
                f"plan has {n} steps — a combine/synthesizer step must read the prior "
                f"steps it is supposed to merge"
            )
        # If every step targets the same single worker with no decomposition signal,
        # it's likely a flattened no-op plan.
        if all(s.worker_id == steps[0].worker_id for s in steps) and n > 2:
            violations.append(
                f"all {n} steps route to the same worker '{steps[0].worker_id}' — "
                f"prefer a single direct step unless genuine decomposition is needed"
            )

    return violations


_REPAIR_SYSTEM = (
    "You are Routism's orchestration engine (the Conductor) fixing a BROKEN plan. "
    "A draft plan you produced failed a structural audit. Read the violations, "
    "then return a CORRECTED plan that fixes every one of them.\\n\\n"
    "Output STRICT JSON only, matching exactly:\\n"
    '{"steps":[{"subtask":"<instruction for one worker>","worker_id":"<exact pool id>",'
    '"access_list":[<prior step indices>],"role":"<worker|verifier|synthesizer>"}]}\\n\\n'
    "Rules:\\n"
    "- worker_id MUST be exactly one of the provided pool ids.\\n"
    "- Step 0 has NO prior steps: access_list MUST be [] and its subtask must be "
    "self-contained (never 'extract from previous steps').\\n"
    "- Each later step's access_list may only list PRIOR step indices (smaller number).\\n"
    "- If there are multiple steps, the FINAL step must read the earlier steps it "
    "combines (non-empty access_list) and use role 'synthesizer'.\\n"
    "- Use 1-4 steps; a single self-contained answer needs just 1 step."
)


def _build_repair_user(
    query: str, prior: Workflow, violations: list[str], pool_ids: list[str]
) -> str:
    vio_block = "\\n".join(f"- {v}" for v in violations) if violations else "(none)"
    return (
        f"Pool worker ids (use EXACTLY these): {pool_ids}\\n\\n"
        f"Original user query: {query}\\n\\n"
        f"Your draft plan that FAILED the audit:\\n"
        f"{json.dumps([s.model_dump() for s in prior.steps], indent=2)}\\n\\n"
        f"Audit violations to fix:\\n{vio_block}\\n\\n"
        "Return the CORRECTED plan JSON now, and nothing else."
    )


def _extract_json(text: str) -> dict:
    """Robustly pull the outermost JSON object from an LLM response.

    Handles fenced blocks and stray prose by scanning for the outermost
    balanced {...} rather than relying on a brittle regex.
    """
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    fence = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
    candidate = fence.group(1) if fence else text
    start = candidate.find("{")
    if start == -1:
        raise ValueError(f"no JSON object in orchestrator output: {text!r}")
    depth = 0
    for i in range(start, len(candidate)):
        ch = candidate[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return json.loads(candidate[start : i + 1])
    raise ValueError(f"unbalanced JSON in orchestrator output: {text!r}")


def _looks_like(needles: tuple[str, ...], text: str) -> bool:
    low = text.lower()
    return any(n in low for n in needles)


def _looks_like_synthesis(subtask: str) -> bool:
    return _looks_like(
        ("synthesize", "final answer", "combine", "summarize all", "produce the answer"),
        subtask,
    )


def _looks_like_check(subtask: str) -> bool:
    return _looks_like(
        ("verify", "check", "validate", "confirm", "is correct", "review"),
        subtask,
    )


def _pick_by_role(role: str, settings: Settings) -> str:
    """Engine routing decision: pick a worker whose tags match the role."""
    want = _ROLE_TAG.get(role, "worker")
    for w in settings.workers:
        if want in w.tags:
            return w.id
    # No tagged worker for this role — fall back to the first pool worker
    # (a real task worker), NOT the dedicated orchestrator. Routing a
    # verifier/synthesizer step onto the orchestrator would overload the
    # conductor and break the "dedicated orchestrator" guarantee.
    return settings.workers[0].id


class Toolbox:
    """Tools the engine invokes. Real logic, separate from the model."""

    def __init__(self, brain: Brain, settings: Settings) -> None:
        self.brain = brain
        self.settings = settings

    def decompose(self, query: str, pool_ids: list[str]) -> Workflow:
        """THINKER tool: ask the Brain to decompose `query` into a Workflow.

        NOTE: this does NOT validate worker_ids against the pool — the engine's
        `select_workers` tool repairs off-pool/placeholder ids afterward. We only
        parse + structurally validate the shape here.
        """
        messages = [
            {"role": "system", "content": _CONDUCTOR_SYSTEM},
            {"role": "user", "content": _build_user(query, pool_ids)},
        ]
        raw = self.brain.complete(messages, max_tokens=512)
        data = _extract_json(raw)
        return Workflow(**data)

    def assign_roles(self, wf: Workflow) -> Workflow:
        """Engine logic (not the model): stamp each step with a Role.

        The model may PROPOSE roles in its JSON; the engine ENFORCES them so
        orchestration is deterministic and correct (Trinity/Fugu role discipline).
        """
        steps = list(wf.steps)
        n = len(steps)
        for i, st in enumerate(steps):
            if i == n - 1 and _looks_like_synthesis(st.subtask):
                st.role = Role.SYNTHESIZER.value
            elif _looks_like_check(st.subtask):
                st.role = Role.VERIFIER.value
            else:
                st.role = Role.WORKER.value
        return Workflow(steps=steps)

    def reflect(self, query: str, prior: Workflow, rejections: list[tuple[int, str]], pool_ids: list[str]) -> Workflow:
        """REFLECT tool: feed prior plan + verifier rejections back to the Brain
        and get a REVISED workflow. Real engine logic decides what to keep/drop;
        the model proposes the repair."""
        messages = [
            {"role": "system", "content": _REFLECT_SYSTEM},
            {"role": "user", "content": _build_reflect_user(query, prior, rejections, pool_ids)},
        ]
        raw = self.brain.complete(messages, max_tokens=512)
        return Workflow(**_extract_json(raw))

    def repair(self, query: str, prior: Workflow, violations: list[str], pool_ids: list[str]) -> Workflow:
        """REPAIR tool: feed a structurally-audited (but worker-valid) plan + the
        audit violations back to the Brain and get a CORRECTED workflow. This is
        the Conductor self-correcting its own plan instead of blindly retrying
        the same prompt — the live eval showed identical retries just re-fail on
        the same broken JSON/structure from small local models."""
        messages = [
            {"role": "system", "content": _REPAIR_SYSTEM},
            {"role": "user", "content": _build_repair_user(query, prior, violations, pool_ids)},
        ]
        raw = self.brain.complete(messages, max_tokens=512)
        return Workflow(**_extract_json(raw))

    def select_workers(self, wf: Workflow, settings: Settings) -> Workflow:
        """Engine logic: route every step to a real worker by role.

        Fills MISSING worker_ids AND repairs OFF-POOL ones (e.g. the model emits
        "UNKNOWN" or a hallucinated id) — the engine, not the model, owns the
        final routing decision.
        """
        by_id = {w.id: w for w in settings.workers}
        steps = list(wf.steps)
        for st in steps:
            if st.worker_id not in by_id:
                st.worker_id = _pick_by_role(st.role, settings)
        return Workflow(steps=steps)


class OrchestrationEngine:
    """The Conductor. Stateful, tool-driven, separate from the worker pool."""

    def __init__(self, settings: Settings, brain: Brain | None = None) -> None:
        if brain is None:
            brain = make_brain(settings)
        self.settings = settings
        self.brain = brain
        self.tools = Toolbox(brain, settings)
        self.transcript: list[Turn] = []

    def revise(
        self,
        query: str,
        prior: Workflow,
        rejections: list[tuple[int, str]],
        *,
        retries: int = 3,
    ) -> Workflow:
        """Multi-turn REFLECT: produce a revised plan from verifier rejections.

        This is the engine's self-correction loop — distinct from the executor's
        local retry. It records a SYNTHESIZER/Thinker reflect turn in the transcript.
        """
        pool_ids = [w.id for w in self.settings.workers]
        if self.settings.orchestrator_worker_id is None:
            raise OrchestratorNotConfigured(
                "orchestrator_worker_id is not set — the orchestration engine "
                "requires a DEDICATED model and will not silently reuse a task worker."
            )
        last_err: Exception | None = None
        for _ in range(1, retries + 1):
            try:
                wf = self.tools.reflect(query, prior, rejections, pool_ids)
            except (ValueError, json.JSONDecodeError) as e:
                last_err = e
                continue
            wf = self.tools.assign_roles(wf)
            wf = self.tools.select_workers(wf, self.settings)
            try:
                wf = wf.validate_against_pool(set(pool_ids))
            except ValueError as e:
                last_err = e
                continue
            self.transcript.append(
                Turn(Role.THINKER, self.settings.orchestrator.id, f"reflect({len(rejections)} rejections)")
            )
            return wf
        raise OrchestratorNotConfigured(
            f"orchestration engine failed to revise after {retries} attempts: {last_err}"
        )

    def plan(self, query: str, *, retries: int = 3) -> Workflow:
        pool_ids = [w.id for w in self.settings.workers]
        if not pool_ids:
            raise OrchestratorNotConfigured("no workers configured in pool")
        if self.settings.orchestrator_worker_id is None:
            raise OrchestratorNotConfigured(
                "orchestrator_worker_id is not set — the orchestration engine "
                "requires a DEDICATED model and will not silently reuse a task "
                "worker. Set orchestrator_worker_id in routism.yaml."
            )
        last_err: Exception | None = None
        for attempt in range(1, retries + 1):
            try:
                wf = self.tools.decompose(query, pool_ids)
            except (ValueError, json.JSONDecodeError) as e:
                # malformed JSON from the Brain — retry decompose
                last_err = e
                continue
            # Engine REPAIRS a step whose worker_id is unknown/off-pool: the
            # role router fills it from the pool by role, so the engine is robust
            # to the model emitting a placeholder like "UNKNOWN".
            wf = self.tools.assign_roles(wf)
            wf = self.tools.select_workers(wf, self.settings)
            try:
                wf = wf.validate_against_pool(set(pool_ids))
            except ValueError as e:
                # still unresolvable (e.g. no worker matches the needed role) —
                # retry decompose
                last_err = e
                continue
            # Structural/semantic audit (catches plan bugs validate_against_pool
            # misses: step-0 referencing prior steps, a synthesizer reading
            # nothing, forward access refs). If it fails, the Conductor REPAIRS
            # its own plan (feeds the audit back to the Brain) rather than
            # retrying the identical decompose prompt.
            violations = _audit_workflow(wf, query)
            if violations:
                try:
                    wf = self.tools.repair(query, wf, violations, pool_ids)
                except (ValueError, json.JSONDecodeError) as e:
                    last_err = e
                    continue
                wf = self.tools.assign_roles(wf)
                wf = self.tools.select_workers(wf, self.settings)
                try:
                    wf = wf.validate_against_pool(set(pool_ids))
                except ValueError as e:
                    last_err = e
                    continue
                # Re-audit the repaired plan; if still broken, the outer retry
                # loop will decompose fresh.
                if _audit_workflow(wf, query):
                    last_err = ValueError(
                        f"repaired plan still fails audit: {_audit_workflow(wf, query)}"
                    )
                    continue
            self.transcript.append(
                Turn(Role.THINKER, self.settings.orchestrator.id, f"plan({len(wf.steps)} steps)")
            )
            return wf
        raise OrchestratorNotConfigured(
            f"orchestration engine failed to plan after {retries} attempts: {last_err}"
        )

    def safe_plan(self, query: str, *, retries: int = 3) -> tuple[Workflow, bool]:
        """Like `plan()` but degrades gracefully.

        Returns (workflow, used_fallback). If the Conductor (a possibly-weak
        local model) cannot produce a valid + audited plan after `retries`,
        we fall back to a SINGLE direct step that answers the query with the
        first pool worker — instead of raising and failing the whole request.
        This is what prevents a tiny orchestrator from taking down an entire
        query (the live eval saw "2+2" fail entirely when gemma emitted
        truncated/malformed JSON). Orchestration is best-effort; when the
        conductor is too weak, a direct call is strictly better than an error.
        """
        try:
            return self.plan(query, retries=retries), False
        except OrchestratorNotConfigured:
            fallback = Workflow(
                steps=[
                    Step(
                        subtask=query,
                        worker_id=self.settings.workers[0].id,
                        access_list=[],
                        role=Role.WORKER.value,
                    )
                ]
            )
            self.transcript.append(
                Turn(Role.THINKER, self.settings.orchestrator.id, "plan-fallback(single direct step)")
            )
            return fallback, True


def make_brain(settings: Settings) -> Brain:
    """Build the engine's Brain from the DEDICATED orchestrator worker.

    settings.orchestrator raises OrchestratorNotConfigured if none is configured
    (the engine never reuses a task worker — that is the whole point).
    """
    orch = settings.orchestrator

    class _LLMBrain:
        def complete(self, messages, *, max_tokens=512):
            return worker_mod.complete(orch, messages, max_tokens=max_tokens)

    return _LLMBrain()
