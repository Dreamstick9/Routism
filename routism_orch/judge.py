"""Phase 6.C — ENGINE-INTERNAL judge / scoring.

This module is part of the orchestration ENGINE (routism_orch). It judges the
candidate answers produced by the user's black-box worker pool (P6.B fan_out)
using the engine's OWN reserved models — eng-verifier (qwen3:4b, thinking) for
absolute 0-10 scoring and eng-judge2 (deepseek-r1:1.5b, thinking) for pairwise
A/B cross-checks.

HARD BOUNDARY (user, non-negotiable):
  * This code runs the ENGINE's brains ONLY. It reads models from `orch.yaml`
    (reserved) via `engine_client.call_engine_model`. It NEVER imports the app
    worker pool, NEVER calls a user worker, and NEVER appears in the UI. The
    judge is ENGINE-INTERNAL.
  * It consumes candidate answers as plain data (CandidateInput), NOT by
    importing `routism.worker` — that keeps routism_orch dependency-free and
    preserves the ENGINE ≠ WORKERS separation. The P6.E glue maps FanOutResult
    -> CandidateInput.

Output is STRUCTURED and robustly parsed: the verifier is asked for JSON
`{"score": N, "reason": "..."}` but we also tolerate a bare `score: N` line so a
think-y model that leaks reasoning before/after the JSON still scores.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from . import engine_client
from .registry import OrchModel, OrchRegistry
from .engine_client import EngineModelError

# --- prompts ---------------------------------------------------------------

_VERIFIER_SYSTEM = (
    "You are a strict answer VERIFIER for a multi-model orchestration engine. "
    "You are given a TASK (this may be one subtask work order, not the whole multi-step "
    "user goal) and a CANDIDATE ANSWER. Score ONLY whether the answer fulfills THIS task: "
    "(1) matches the stated deliverable and success criteria, (2) coherent / non-hallucinated, "
    "(3) complete for THIS step only. Do NOT penalize missing work that belongs to other "
    "steps (e.g. do not require unit tests if this task is design-only). Output ONLY JSON "
    "{\"score\": <int 0-10>, \"reason\": \"<one short sentence>\"}. "
    "0 = wrong/garbage for this task; 10 = fully meets this task's criteria."
)

_NODE_VERIFIER_SYSTEM = _VERIFIER_SYSTEM

_JUDGE2_SYSTEM = (
    "You are a cross-check JUDGE for a multi-model orchestration engine. You are "
    "given a QUESTION and TWO candidate answers (A and B). Decide which is BETTER "
    "on correctness, coherence, and completeness for EVERY requested deliverable. "
    "Multi-part questions (design + code + tests + notes, etc.): prefer the answer "
    "that covers each deliverable as a concrete, separated section. Do NOT prefer "
    "brevity when it omits or compresses a requested part. Output ONLY one JSON "
    "object: {\"winner\": \"A\" | \"B\", \"reason\": \"<one short sentence>\"}. "
    "If coverage and correctness are truly equal, pick the better structured one."
)

_SCORE_RE = re.compile(r"score\"?\s*:\s*(\d+(?:\.\d+)?)", re.IGNORECASE)
_REASON_RE = re.compile(r"reason\"?\s*:\s*\"([^\"]*)\"", re.IGNORECASE)
_WINNER_RE = re.compile(r"winner\"?\s*:\s*\"?([AB])\"?", re.IGNORECASE)
# Free-text fallbacks when tiny thinking models skip JSON
_WINNER_A_RE = re.compile(
    r"\b(?:winner\s*(?:is|:)?\s*A|prefer(?:s|ring)?(?:\s+\w+){0,2}\s+A|"
    r"candidate\s+A\s+(?:is\s+)?(?:better|wins|more)|"
    r"choose\s+A|pick\s+A|A\s+is\s+(?:better|superior|clearer|more\s+complete))\b",
    re.IGNORECASE,
)
_WINNER_B_RE = re.compile(
    r"\b(?:winner\s*(?:is|:)?\s*B|prefer(?:s|ring)?(?:\s+\w+){0,2}\s+B|"
    r"candidate\s+B\s+(?:is\s+)?(?:better|wins|more)|"
    r"choose\s+B|pick\s+B|B\s+is\s+(?:better|superior|clearer|more\s+complete))\b",
    re.IGNORECASE,
)


@dataclass
class CandidateInput:
    """Plain-data candidate the judge scores. No app-package import needed.

    `answer` is None when the worker failed (P6.B isolation) — the judge then
    assigns score 0 with a reason noting the failure, rather than calling the
    engine on garbage.
    """

    worker_id: str
    answer: str | None
    role: str | None = None
    error: str | None = None
    elapsed_ms: float = 0.0


@dataclass
class CandidateScore:
    worker_id: str
    role: str | None
    score: float
    reason: str
    error: str | None = None
    elapsed_ms: float = 0.0

    def to_ui_score(self) -> dict:
        """Shape the /scores SSE event + ParallelCandidate carry in P6.E."""
        return {
            "worker_id": self.worker_id,
            "score": self.score,
            "reason": self.reason,
        }


@dataclass
class PairwiseResult:
    winner: str  # worker_id of the winner
    loser: str   # worker_id of the loser
    reason: str

    def to_ui(self) -> dict:
        return {"winner": self.winner, "loser": self.loser, "reason": self.reason}


def _parse_score_json(text: str) -> tuple[float | None, str]:
    """Best-effort parse of a verifier response into (score, reason).

    Strategy: try strict JSON first; if that fails, fall back to regex for
    `score:` / `reason:`. Returns (None, reason) when no score is found so the
    caller can decide how to handle an unparseable verdict.
    """
    reason = ""
    # 1) strict JSON
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            s = obj.get("score")
            r = obj.get("reason", "")
            if s is not None:
                return float(s), str(r)
    except (json.JSONDecodeError, ValueError, TypeError):
        pass
    # 2) regex fallback — take the LAST score:/reason: match, because qwen3
    # thinking models emit the structured verdict at the TAIL of the reasoning
    # trace (the head is free-form CoT prose). `.findall` + `[-1]` avoids
    # grabbing a score mentioned inside the prose reasoning.
    scores = _SCORE_RE.findall(text)
    reasons = _REASON_RE.findall(text)
    score = float(scores[-1]) if scores else None
    if reasons:
        reason = reasons[-1]
    return score, reason


def _parse_winner_json(text: str) -> tuple[str | None, str]:
    """Parse a judge2 pairwise response into (winner_label, reason)."""
    reason = ""
    raw = (text or "").strip()
    if not raw:
        return None, ""
    # 1) full-document JSON
    try:
        obj = json.loads(raw)
        if isinstance(obj, dict):
            w = obj.get("winner")
            r = obj.get("reason", "")
            if str(w).upper() in ("A", "B"):
                return str(w).upper(), str(r)
    except (json.JSONDecodeError, ValueError, TypeError):
        pass
    # 2) embedded JSON object anywhere in the trace
    for m in re.finditer(r"\{[^{}]*\}", raw):
        try:
            obj = json.loads(m.group(0))
            if isinstance(obj, dict) and str(obj.get("winner", "")).upper() in ("A", "B"):
                return str(obj["winner"]).upper(), str(obj.get("reason", "") or "")
        except (json.JSONDecodeError, ValueError, TypeError):
            continue
    # 3) winner: A/B regex — take the LAST match (verdict at tail of CoT)
    winners = _WINNER_RE.findall(raw)
    reasons = _REASON_RE.findall(raw)
    winner = winners[-1].upper() if winners else None
    if reasons:
        reason = reasons[-1]
    if winner in ("A", "B"):
        return winner, reason
    # 4) free-text “prefer A/B” patterns — last decisive mention wins
    a_hits = list(_WINNER_A_RE.finditer(raw))
    b_hits = list(_WINNER_B_RE.finditer(raw))
    if a_hits or b_hits:
        last_a = a_hits[-1].start() if a_hits else -1
        last_b = b_hits[-1].start() if b_hits else -1
        if last_a > last_b:
            return "A", reason or "parsed free-text prefer A"
        if last_b > last_a:
            return "B", reason or "parsed free-text prefer B"
    return None, reason or raw[:160]


def score_one(
    verifier: OrchModel,
    query: str,
    cand: CandidateInput,
    *,
    base_url: str = engine_client._DEFAULT_OLLAMA_URL,
    success_criteria: str = "",
    overall_goal: str = "",
) -> CandidateScore:
    """Absolute 0-10 score for one candidate using eng-verifier.

    ``query`` should be the node work order / task under test (not only the full
    multi-step user goal). Optional success_criteria narrows the bar.
    """
    if cand.answer is None or cand.error:
        return CandidateScore(
            worker_id=cand.worker_id,
            role=cand.role,
            score=0.0,
            reason=f"worker failed: {cand.error or 'no answer'}",
            error=cand.error,
            elapsed_ms=cand.elapsed_ms,
        )
    goal_block = (
        f"OVERALL USER GOAL (context only — do not grade other steps):\n{overall_goal}\n\n"
        if (overall_goal or "").strip()
        else ""
    )
    crit_block = (
        f"SUCCESS CRITERIA FOR THIS STEP ONLY:\n{success_criteria}\n\n"
        if (success_criteria or "").strip()
        else ""
    )
    messages = [
        {"role": "system", "content": _NODE_VERIFIER_SYSTEM},
        {
            "role": "user",
            "content": (
                f"{goal_block}"
                f"THIS STEP TASK:\n{query}\n\n"
                f"{crit_block}"
                f"CANDIDATE ANSWER (worker={cand.worker_id}):\n{cand.answer}\n\n"
                "Score only this step. Output JSON only."
            ),
        },
    ]
    try:
        resp = engine_client.call_engine_model(
            verifier, messages, base_url=base_url,
            temperature=0.0, max_tokens=768, timeout=120.0, think_override=False,
        )
    except EngineModelError as e:
        return CandidateScore(
            worker_id=cand.worker_id, role=cand.role, score=0.0,
            reason=f"verifier error: {e}", error=str(e), elapsed_ms=cand.elapsed_ms,
        )
    # Ollama's qwen3 thinking models emit the actual verdict in the `reasoning`
    # field and leave `content` empty within the token budget. Read the model's
    # own JSON from whichever field it populated (content takes priority).
    verdict = resp.content or (resp.thinking or "")
    score, reason = _parse_score_json(verdict)
    if score is None:
        # Unparseable verdict -> conservative mid score + flag, never crash.
        return CandidateScore(
            worker_id=cand.worker_id, role=cand.role, score=5.0,
            reason=f"verifier returned unparseable verdict: {verdict[:120]!r}",
            elapsed_ms=cand.elapsed_ms,
        )
    # clamp to 0-10
    score = max(0.0, min(10.0, score))
    return CandidateScore(
        worker_id=cand.worker_id, role=cand.role, score=score,
        reason=reason or "(no reason given)", elapsed_ms=cand.elapsed_ms,
    )


def pairwise(
    judge2: OrchModel,
    query: str,
    a: CandidateInput,
    b: CandidateInput,
    *,
    base_url: str = engine_client._DEFAULT_OLLAMA_URL,
) -> PairwiseResult:
    """A/B cross-check between the two best candidates using eng-judge2.

    `a` and `b` are ordered (we map whichever the engine picked as top-2 to A/B).
    Returns which worker_id won. Falls back to the HIGHER pre-score if judge2 is
    unparseable/fails, so the engine never loses the comparison on a judge glitch.
    """
    a_text = a.answer or f"[FAILED: {a.error or 'no answer'}]"
    b_text = b.answer or f"[FAILED: {b.error or 'no answer'}]"
    messages = [
        {"role": "system", "content": _JUDGE2_SYSTEM},
        {
            "role": "user",
            "content": (
                f"QUESTION:\n{query}\n\n"
                f"CANDIDATE A (worker={a.worker_id}):\n{a_text}\n\n"
                f"CANDIDATE B (worker={b.worker_id}):\n{b_text}\n\n"
                "Decide which candidate better covers ALL deliverables in the question.\n"
                "Respond with exactly one line of JSON and nothing else, e.g.\n"
                '{"winner":"A","reason":"more complete multi-section coverage"}\n'
                "or\n"
                '{"winner":"B","reason":"clearer and covers all parts"}'
            ),
        },
    ]
    try:
        resp = engine_client.call_engine_model(
            judge2, messages, base_url=base_url,
            temperature=0.0, max_tokens=768, timeout=120.0, think_override=False,
        )
        # Prefer content; if empty or unparseable, also scan thinking (r1 models)
        blob = (resp.content or "").strip()
        think = (resp.thinking or "").strip()
        label, reason = _parse_winner_json(blob)
        if label is None and think:
            label2, reason2 = _parse_winner_json(think)
            if label2 is not None:
                label, reason = label2, reason2
            elif not reason:
                reason = reason2
        if label is None and blob and think:
            # Combined tail often holds the JSON after CoT
            label, reason = _parse_winner_json(think + "\n" + blob)
    except EngineModelError as e:
        label, reason = None, f"judge2 error: {e}"
    if label == "A":
        return PairwiseResult(winner=a.worker_id, loser=b.worker_id, reason=reason)
    if label == "B":
        return PairwiseResult(winner=b.worker_id, loser=a.worker_id, reason=reason)
    # unparseable / failed -> do NOT invent a winner; let caller decide by score
    return PairwiseResult(winner="", loser="", reason=reason or "unparseable")


def judge_all(
    registry: OrchRegistry,
    query: str,
    candidates: list[CandidateInput],
    *,
    base_url: str = engine_client._DEFAULT_OLLAMA_URL,
    score_only: bool = False,
) -> tuple[list[CandidateScore], PairwiseResult | None]:
    """Score every candidate with eng-verifier; optionally pairwise-check top-2.

    Returns (scores, pairwise). `pairwise` is None when fewer than 2 real
    candidates exist, when ``score_only=True``, or when judge2 is unavailable.

    ``score_only=True`` is the Conductor default for layer scoring: absolute
    0–10 only, no eng-judge2 pairwise. Pairwise is wrong when candidates are
    different subtasks (incomparable prompts) and is pure latency waste.
    Parallel mode and k-sample ties keep ``score_only=False`` so top-2 can
    still be cross-checked.

    ENGINE-INTERNAL: uses only reserved engine models from `registry`.
    """
    verifier = registry.verifier()
    judge2 = registry.judge2()
    if verifier is None:
        raise EngineModelError("orch.yaml has no role=verifier engine model")

    scores: list[CandidateScore] = []
    for cand in candidates:
        scores.append(score_one(verifier, query, cand, base_url=base_url))

    pairwise_res: PairwiseResult | None = None
    if score_only:
        return scores, None

    real = [c for c in candidates if c.answer and not c.error]
    if judge2 is not None and len(real) >= 2:
        # top-2 by score (or by input order for ties); pairwise over them
        top2 = sorted(real, key=lambda c: _score_of(scores, c.worker_id), reverse=True)[:2]
        pairwise_res = pairwise(judge2, query, top2[0], top2[1], base_url=base_url)
    return scores, pairwise_res


def _score_of(scores: list[CandidateScore], worker_id: str) -> float:
    for s in scores:
        if s.worker_id == worker_id:
            return s.score
    return 0.0
