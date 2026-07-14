"""Phase 6.D — synthesis (merge candidates into final answer).

This module is part of the orchestration ENGINE (routism_orch). After the judge
(P6.C) scores every fan-out candidate, the synthesizer takes the top-K correct
answers and merges them into a single FINAL.

Default merge engines:
  * eng-thinker (qwen2.5:7b) via `synthesize` / sectioned merge — product path
  * Pool-merge is DISABLED (ENGINE ≠ WORKERS). CONDUCTOR_POOL_MERGE default OFF.

A verify gate (eng-verifier) scores that FINAL; if it's REJECTED the
synthesizer gets ONE retry with the verifier's critique.

Data contract:
  * Consumes plain data (list[CandidateScore]), NOT FanOutResult.
  * Trace strategy: sectioned-merge | merge-top-k | best_sample_fallback.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

import httpx

from . import engine_client
from .engine_client import EngineModelError
from .judge import CandidateScore, PairwiseResult
from .registry import OrchModel, OrchRegistry


def merge_fallback_enabled() -> bool:
    """CONDUCTOR_MERGE_FALLBACK default ON: keep best sample if merge is worse."""
    v = os.environ.get("CONDUCTOR_MERGE_FALLBACK", "1").strip().lower()
    return v not in ("0", "false", "no", "off")


def pool_merge_enabled() -> bool:
    """CONDUCTOR_POOL_MERGE default OFF (IRON RULE: workers never synthesize).

    Set CONDUCTOR_POOL_MERGE=1 only for offline experiments — product path
    always uses eng-thinker.
    """
    v = os.environ.get("CONDUCTOR_POOL_MERGE", "0").strip().lower()
    return v in ("1", "true", "yes", "on")


# Preferred capability tags for the merge aggregator (MoA research: summarize /
# reasoning / explain / chat workers are better synthesizers than pure code).
_MERGE_TAGS = frozenset({"summarize", "reasoning", "explain", "chat"})

# ---------------------------------------------------------------------------
# prompts
# ---------------------------------------------------------------------------

_SYNTHESIZER_SYSTEM = (
    "You are the SYNTHESIZER for a multi-model orchestration engine (engine-only). "
    "You receive the USER GOAL and STEP OUTPUTS from specialist workers.\n"
    "HARD RULES:\n"
    "1. Produce ONE final answer with CLEAR SECTIONS matching successful steps "
    "(use the step titles/intents as headings).\n"
    "2. Preserve concrete artifacts (code, tables, specs) from high-scoring steps; "
    "do not rewrite them into a thin summary that loses content.\n"
    "3. If a step FAILED or has no output, add a section "
    "### {step title}\\nNOT PRODUCED — {error or reason}. "
    "NEVER invent tests, code, or claims for failed steps.\n"
    "4. Do not claim the whole goal is complete if any required step failed.\n"
    "5. Output ONLY the final answer text — no JSON wrapper, no meta-commentary "
    "about being a synthesizer."
)

_SECTIONED_SYNTH_SYSTEM = _SYNTHESIZER_SYSTEM

_VERIFY_SYSTEM = (
    "You are a VERIFY-GATE checker. You are given a QUESTION and a proposed "
    "FINAL ANSWER that was synthesized from multiple candidate answers. Judge "
    "the FINAL on correctness, coherence, and completeness. Output ONLY JSON: "
    '{"accept": <true|false>, "score": <int 0-10>, "reason": "<one sentence>"}. '
    "accept=false if the answer is wrong, contradictory, or missing critical "
    "information. A score below 7 should reject."
)

_REJECT_THRESHOLD = 7

# ---------------------------------------------------------------------------
# data types
# ---------------------------------------------------------------------------


def _build_synth_user(query: str, candidates: list[CandidateScore], answers: dict[str, str]) -> str:
    """Build the synthesizer prompt showing each candidate with its score."""
    parts = [
        f"USER GOAL:\n{query}\n\n",
        "STEP OUTPUTS (merge into sectioned final; mark failures honestly):\n",
    ]
    for c in candidates:
        ans = answers.get(c.worker_id)
        if ans is None and c.error:
            ans = f"[FAILED: {c.error}]"
        elif ans is None:
            ans = "(no answer)"
        role = c.role or c.worker_id
        parts.append(
            f"### Step {role} | worker={c.worker_id} | score={c.score}/10\n"
            f"Judge note: {c.reason}\n"
            f"OUTPUT:\n{ans}\n"
        )
    parts.append(
        "\nAssemble the final answer with one section per successful step. "
        "For failed steps use NOT PRODUCED. Do not invent missing deliverables."
    )
    return "\n".join(parts)


def build_sectioned_synth_user(
    query: str,
    *,
    step_rows: list[dict[str, Any]],
) -> str:
    """Build sectioned merge prompt from explicit step rows.

    Each row: {id, title/intent, result|None, error|None, score|None, worker_id}
    """
    parts = [
        f"USER GOAL:\n{query}\n\n",
        "STEP OUTPUTS:\n",
    ]
    for row in step_rows:
        sid = row.get("id") or "?"
        title = row.get("title") or row.get("intent") or sid
        worker = row.get("worker_id") or "?"
        score = row.get("score")
        score_s = f"{score}/10" if score is not None else "n/a"
        err = row.get("error")
        result = row.get("result")
        if err or not result:
            body = f"NOT PRODUCED — {err or 'no output'}"
        else:
            body = str(result)
        parts.append(
            f"### {sid}: {title} | worker={worker} | score={score_s}\n{body}\n"
        )
    parts.append(
        "\nProduce the final answer with sections for each step. "
        "Keep successful artifacts rich. Failed steps must say NOT PRODUCED."
    )
    return "\n".join(parts)


def _build_verify_user(query: str, draft: str) -> str:
    """Build the verify-gate prompt."""
    return (
        f"QUESTION: {query}\n\n"
        f"PROPOSED FINAL ANSWER:\n{draft}\n\n"
        f"Output JSON only."
    )


_ACCEPT_RE = re.compile(r'accept"?\s*:\s*(true|false)', re.IGNORECASE)
_VERIFY_SCORE_RE = re.compile(r'score"?\s*:\s*(\d+(?:\.\d+)?)', re.IGNORECASE)


def _parse_verify_json(text: str) -> tuple[bool, int, str]:
    """Parse the verifier's JSON verdict from text (content or reasoning).

    Returns (accepted: bool, score: int, reason: str).
    """
    # 1) strict JSON (the whole text)
    try:
        d = json.loads(text)
        accept = bool(d.get("accept", True))
        score = int(float(d.get("score", 0)))
        reason = str(d.get("reason", ""))
        return accept, score, reason
    except (json.JSONDecodeError, ValueError, TypeError):
        pass

    # 2) regex fallback — LAST match for JSON-in-prose (qwen3 thinking tail)
    all_accept = _ACCEPT_RE.findall(text)
    accept = all_accept[-1].lower() == "true" if all_accept else True
    all_score = _VERIFY_SCORE_RE.findall(text)
    score = int(float(all_score[-1])) if all_score else 0
    reason = "unparseable verify verdict"
    return accept, score, reason


# ---------------------------------------------------------------------------
# pool-merge helpers (Conductor MoA aggregator)
# ---------------------------------------------------------------------------


def pick_merge_worker(
    workers: list[Any] | None,
    health: dict[str, bool] | None = None,
) -> Any | None:
    """Pick the best pool worker to act as merge aggregator.

    Scoring (higher is better):
      * +1 per preferred tag hit among {summarize, reasoning, explain, chat}
      * +1 if healthy (when health map is provided / default healthy)

    Unhealthy workers are excluded when any healthy worker exists. Tie-break
    by more tag hits, then stable worker id. Returns the worker object or None.
    """
    if not workers:
        return None

    health_map = health if health is not None else {}
    # Default: unknown workers treated as healthy when no map entry.
    def _is_healthy(wid: str) -> bool:
        if health is None:
            return True
        return bool(health_map.get(wid, True))

    ranked: list[tuple[float, int, str, Any]] = []
    for w in workers:
        wid = getattr(w, "id", None)
        if not wid:
            continue
        tags = {str(t).lower() for t in (getattr(w, "tags", None) or [])}
        tag_hits = len(tags & _MERGE_TAGS)
        healthy = _is_healthy(str(wid))
        score = float(tag_hits) + (1.0 if healthy else 0.0)
        ranked.append((score, tag_hits, str(wid), w))

    if not ranked:
        return None

    healthy_only = [r for r in ranked if _is_healthy(r[2])]
    pool = healthy_only if healthy_only else ranked
    pool.sort(key=lambda r: (-r[0], -r[1], r[2]))
    return pool[0][3]


def _chat_completions_url(base_url: str) -> str:
    """Mirror routism.worker.chat_completions_url without importing worker."""
    url = (base_url or "").rstrip("/")
    if url.endswith("/chat/completions"):
        return url
    if url.endswith("/v1"):
        return url + "/chat/completions"
    return url + "/chat/completions"


def _pool_worker_complete(
    worker: Any,
    messages: list[dict],
    *,
    max_tokens: int = 2048,
    timeout: float = 120.0,
) -> str:
    """POST OpenAI-compatible chat/completions to a pool worker; return text."""
    base = getattr(worker, "base_url", "") or ""
    url = _chat_completions_url(base)
    model = getattr(worker, "model", "") or ""
    headers: dict[str, str] = {"content-type": "application/json"}
    raw_key = getattr(worker, "api_key", None)
    if raw_key:
        key = raw_key
        try:
            from routism.crypto_keys import resolve_api_key

            key = resolve_api_key(raw_key) or raw_key
        except Exception:
            pass
        if key:
            headers["authorization"] = f"Bearer {key}"

    tok = max_tokens
    if getattr(worker, "max_tokens", None):
        tok = min(int(max_tokens), int(worker.max_tokens))
    to = timeout
    if getattr(worker, "timeout_s", None):
        to = min(float(timeout), float(worker.timeout_s))

    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": tok,
    }
    with httpx.Client(timeout=to) as client:
        resp = client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()
    text = data["choices"][0]["message"]["content"]
    return (text or "").strip()


def _best_sample(
    candidates: list[CandidateScore],
    answers: dict[str, str],
) -> tuple[str | None, float, str]:
    """Return (best_worker_id, best_score, best_text) among non-empty answers."""
    best_id: str | None = None
    best_score = -1.0
    best_text = ""
    for c in candidates:
        ans = (answers.get(c.worker_id) or "").strip()
        if not ans or c.error:
            continue
        if float(c.score) > best_score:
            best_score = float(c.score)
            best_id = c.worker_id
            best_text = ans
    return best_id, best_score, best_text


def _apply_merge_quality_fallback(
    draft: str,
    candidates: list[CandidateScore],
    answers: dict[str, str],
    *,
    engine_id: str,
    strategy: str,
) -> tuple[str, dict]:
    """Shared post-merge best-sample fallback used by both synthesize paths."""
    best_id, best_score, best_text = _best_sample(candidates, answers)

    used_best_sample = False
    out_strategy = strategy
    out_engine = engine_id
    out_draft = draft

    if not out_draft:
        out_draft = best_text or answers.get(candidates[0].worker_id, "no synthesis produced")
        if merge_fallback_enabled() and best_text:
            out_strategy = "best_sample_fallback"
            used_best_sample = True
            out_engine = best_id or engine_id
    elif merge_fallback_enabled() and best_text:
        # Prefer best sample when synthesis errored or clearly weaker (MoA lesson).
        synth_bad = out_draft.startswith("synthesis error:")
        if synth_bad:
            out_draft = best_text
            out_strategy = "best_sample_fallback"
            used_best_sample = True
            out_engine = best_id or engine_id
        elif best_score >= 7.0 and len(out_draft) < max(40, int(0.35 * len(best_text))):
            out_draft = best_text
            out_strategy = "best_sample_fallback"
            used_best_sample = True
            out_engine = best_id or engine_id

    trace = {
        "engine": out_engine,
        "strategy": out_strategy,
        "contributors": [c.worker_id for c in candidates],
        "draft": out_draft,
        "best_sample_id": best_id,
        "best_sample_score": best_score if best_id else None,
        "used_best_sample_fallback": used_best_sample,
    }
    return out_draft, trace


# ---------------------------------------------------------------------------
# public api
# ---------------------------------------------------------------------------


def stitch_step_rows(query: str, step_rows: list[dict[str, Any]]) -> str:
    """Deterministic sectioned merge: preserve full successful step artifacts.

    This is the product default synthesizer for Conductor — no content loss from
    a weak rewrite. Failed steps are marked NOT PRODUCED honestly.
    """
    parts = [
        f"# Combined answer\n\n## User goal\n\n{query}\n\n"
        f"## Specialist steps\n\n"
        f"The following sections are full artifacts from parallel specialists "
        f"(design / implement / test / notes as assigned).\n",
    ]
    any_ok = False
    for row in step_rows:
        sid = row.get("id") or "?"
        title = row.get("title") or row.get("intent") or sid
        err = row.get("error")
        result = row.get("result")
        worker = row.get("worker_id") or "?"
        if result and not err:
            any_ok = True
            parts.append(
                f"\n## Step {sid}: {title}\n\n"
                f"### Source worker\n\n`{worker}`\n\n"
                f"### Deliverable body\n\n{result}\n"
            )
        else:
            parts.append(
                f"\n## Step {sid}: {title}\n\n"
                f"NOT PRODUCED — {err or 'no output'}\n"
            )
    if not any_ok:
        return (
            "Conductor DAG produced no successful subtask outputs. "
            + "; ".join(
                f"{r.get('id')}@{r.get('worker_id')}: {r.get('error') or 'no answer'}"
                for r in step_rows
            )
        )
    parts.append(
        "\n---\n_Assembled by Routism Conductor from specialist steps "
        "(failed steps listed as NOT PRODUCED)._\n"
    )
    return "".join(parts)


def synthesize(
    thinker: OrchModel,
    query: str,
    candidates: list[CandidateScore],
    answers: dict[str, str],
    *,
    base_url: str = "http://localhost:11434/v1",
    max_tokens: int = 2048,
    timeout: float = 120.0,
    step_rows: list[dict[str, Any]] | None = None,
) -> tuple[str, dict]:
    """Merge into final answer (engine-owned).

    Prefer deterministic sectioned stitch when step_rows present (preserves
    artifacts). Optional eng-thinker rewrite when CONDUCTOR_LLM_MERGE=1.
    """
    if not candidates and not step_rows:
        return (
            "No worker responded to this query.",
            {"engine": thinker.id, "contributors": [], "draft": "", "strategy": "sectioned-merge"},
        )

    # Default: stitch specialist steps (preserve all artifacts). Optional polish
    # via CONDUCTOR_LLM_MERGE=1 (can shorten; off by default after eval).
    skip_polish = os.environ.get("CONDUCTOR_LLM_MERGE", "0").strip().lower() not in (
        "1", "true", "yes", "on",
    )
    if step_rows and skip_polish:
        draft = stitch_step_rows(query, step_rows)
        return _apply_merge_quality_fallback(
            draft,
            candidates,
            answers,
            engine_id=thinker.id,
            strategy="sectioned-stitch",
        )
    if step_rows and not skip_polish:
        stitched = stitch_step_rows(query, step_rows)
        if "no successful subtask" in stitched.lower():
            return _apply_merge_quality_fallback(
                stitched,
                candidates,
                answers,
                engine_id=thinker.id,
                strategy="sectioned-stitch",
            )
        polish_msgs = [
            {
                "role": "system",
                "content": (
                    "You polish a multi-specialist assembly into the best final answer.\n"
                    "HARD RULES:\n"
                    "1. Keep EVERY concrete artifact from the specialists (code, tests, "
                    "tables, specs). Do not drop sections.\n"
                    "2. Use clear ## headings for each deliverable the user asked for.\n"
                    "3. Improve clarity and completeness using only provided material; "
                    "do not invent missing work. Failed steps stay NOT PRODUCED.\n"
                    "4. Output ONLY the final answer."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"USER GOAL:\n{query}\n\n"
                    f"ASSEMBLED SPECIALIST OUTPUTS:\n{stitched}\n\n"
                    "Produce the polished multi-section final answer now."
                ),
            },
        ]
        try:
            r = engine_client.call_engine_model(
                thinker,
                polish_msgs,
                base_url=base_url,
                max_tokens=max_tokens,
                timeout=timeout,
                temperature=0.0,
            )
            draft = (r.content or r.thinking or "").strip()
            if not draft or len(draft) < 80:
                draft = stitched
            strategy = "sectioned-stitch+polish"
        except EngineModelError:
            draft = stitched
            strategy = "sectioned-stitch"
        return _apply_merge_quality_fallback(
            draft,
            candidates,
            answers,
            engine_id=thinker.id,
            strategy=strategy,
        )

    if step_rows:
        user = build_sectioned_synth_user(query, step_rows=step_rows)
    else:
        user = _build_synth_user(query, candidates, answers)
    msgs = [
        {"role": "system", "content": _SECTIONED_SYNTH_SYSTEM},
        {"role": "user", "content": user},
    ]
    try:
        r = engine_client.call_engine_model(
            thinker, msgs,
            base_url=base_url,
            max_tokens=max_tokens,
            timeout=timeout,
            temperature=0.0,
        )
        draft = r.content or r.thinking or ""
    except EngineModelError as e:
        draft = f"synthesis error: {e}"
    draft = draft.strip()
    if step_rows and (not draft or draft.startswith("synthesis error")):
        draft = stitch_step_rows(query, step_rows)

    return _apply_merge_quality_fallback(
        draft,
        candidates,
        answers,
        engine_id=thinker.id,
        strategy="sectioned-merge",
    )


def synthesize_with_pool(
    query: str,
    candidates: list[CandidateScore],
    answers: dict[str, str],
    registry: OrchRegistry,
    workers: list[Any] | None = None,
    *,
    health: dict[str, bool] | None = None,
    ollama_base_url: str = "http://localhost:11434",
    max_tokens: int = 2048,
    timeout: float = 120.0,
    step_rows: list[dict[str, Any]] | None = None,
) -> tuple[str, dict]:
    """Merge via eng-thinker only (product). Pool merge is opt-in experiment only.

    IRON RULE: workers never synthesize. Even if CONDUCTOR_POOL_MERGE=1 is set,
    product Conductor path should pass step_rows and use engine.
    """
    thinker = registry.coordinator()
    thinker_id = thinker.id if thinker else "eng-thinker"
    base_url = ollama_base_url if "/v1" in (ollama_base_url or "") else (
        (ollama_base_url or "http://localhost:11434").rstrip("/") + "/v1"
    )
    # Product default: always engine sectioned merge.
    if not pool_merge_enabled() or not workers:
        if thinker is None:
            return (
                "No synthesizer available.",
                {"engine": thinker_id, "contributors": [], "draft": "", "strategy": "sectioned-merge"},
            )
        return synthesize(
            thinker,
            query,
            candidates,
            answers,
            base_url=base_url,
            max_tokens=max_tokens,
            timeout=timeout,
            step_rows=step_rows,
        )

    if not candidates:
        return (
            "No worker responded to this query.",
            {"engine": thinker_id, "contributors": [], "draft": "", "strategy": "merge-top-k"},
        )

    user = _build_synth_user(query, candidates, answers)
    msgs = [
        {"role": "system", "content": _SYNTHESIZER_SYSTEM},
        {"role": "user", "content": user},
    ]

    strategy = "merge-top-k"
    engine_id = thinker_id
    draft = ""

    merger = None
    if pool_merge_enabled() and workers:
        merger = pick_merge_worker(workers, health)

    if merger is not None:
        try:
            draft = _pool_worker_complete(
                merger, msgs, max_tokens=max_tokens, timeout=timeout
            )
            if draft:
                strategy = "pool-merge"
                engine_id = str(getattr(merger, "id", "pool-worker"))
            else:
                # empty pool response — fall through to eng-thinker
                merger = None
        except Exception as e:
            draft = f"synthesis error: {e}"
            # Prefer eng-thinker recovery over immediate best-sample when available
            merger = None

    if strategy != "pool-merge":
        if thinker is None:
            if not draft:
                draft = f"synthesis error: no eng-thinker available"
        else:
            try:
                r = engine_client.call_engine_model(
                    thinker,
                    msgs,
                    base_url=base_url,
                    max_tokens=max_tokens,
                    timeout=timeout,
                )
                eng_draft = (r.content or r.thinking or "").strip()
                if eng_draft:
                    draft = eng_draft
                    strategy = "merge-top-k"
                    engine_id = thinker.id
                elif not draft:
                    draft = ""
            except EngineModelError as e:
                if not draft or draft.startswith("synthesis error:"):
                    draft = f"synthesis error: {e}"
                strategy = "merge-top-k"
                engine_id = thinker.id

    return _apply_merge_quality_fallback(
        draft.strip() if draft else "",
        candidates,
        answers,
        engine_id=engine_id,
        strategy=strategy,
    )


def apply_merge_fallback_after_verify(
    final_text: str,
    verify_trace: dict,
    candidates: list[CandidateScore],
    answers: dict[str, str],
    *,
    margin: float = 1.0,
) -> tuple[str, dict]:
    """If verify rejects merge and a high-scoring sample exists, use that sample."""
    if not merge_fallback_enabled():
        return final_text, verify_trace
    if verify_trace.get("accepted"):
        return final_text, verify_trace
    best_id, best_score, best_text = _best_sample(candidates, answers)
    if best_text and best_score >= 6.0:
        vt = dict(verify_trace)
        vt["used_best_sample_fallback"] = True
        vt["best_sample_id"] = best_id
        vt["best_sample_score"] = best_score
        return best_text, vt
    return final_text, verify_trace


def verify_and_refine(
    verifier: OrchModel,
    thinker: OrchModel,
    query: str,
    draft: str,
    *,
    base_url: str = "http://localhost:11434/v1",
    timeout: float = 120.0,
) -> tuple[str, dict]:
    """Run a verify gate on the synthesized draft. If rejected, give the
    synthesizer ONE retry with the verifier's critique, then verify again.
    Returns (final_text, verify_trace_dict).
    """
    # --- gate 1 ---
    verif = _do_verify(verifier, query, draft, base_url=base_url, timeout=timeout)
    if verif["accept"]:
        return draft, {"gates": [verif], "accepted": True, "retries": 0}

    # --- one retry with critique ---
    critique_user = (
        f"Your previous answer was REJECTED by the verify gate.\n"
        f"REJECTION REASON: {verif['reason']} (score {verif['score']}/10)\n\n"
        f"ORIGINAL QUESTION: {query}\n\n"
        f"YOUR REJECTED ANSWER: {draft}\n\n"
        f"Fix the issues and produce a corrected final answer. Output only the new answer text."
    )
    msgs = [
        {"role": "system", "content": _SYNTHESIZER_SYSTEM},
        {"role": "user", "content": critique_user},
    ]
    try:
        r = engine_client.call_engine_model(
            thinker, msgs,
            base_url=base_url,
            max_tokens=2048,
            timeout=timeout,
        )
        retry_draft = r.content or r.thinking or ""
    except EngineModelError:
        retry_draft = draft   # unrefineable — return original
    retry_draft = retry_draft.strip() or draft

    # --- gate 2 ---
    verif2 = _do_verify(verifier, query, retry_draft, base_url=base_url, timeout=timeout)
    if verif2["accept"]:
        return retry_draft, {"gates": [verif, verif2], "accepted": True, "retries": 1}

    # still rejected — return best draft
    return draft, {"gates": [verif, verif2], "accepted": False, "retries": 1}


def _do_verify(
    verifier: OrchModel,
    query: str,
    draft: str,
    *,
    base_url: str = "http://localhost:11434/v1",
    timeout: float = 120.0,
) -> dict[str, object]:
    """Single verify-gate call. Returns {accept, score, reason}."""
    user = _build_verify_user(query, draft)
    msgs = [
        {"role": "system", "content": _VERIFY_SYSTEM},
        {"role": "user", "content": user},
    ]
    try:
        r = engine_client.call_engine_model(
            verifier, msgs,
            base_url=base_url,
            max_tokens=768,
            timeout=timeout,
        )
        text = r.content or r.thinking or ""
    except EngineModelError as e:
        return {"accept": True, "score": 5, "reason": f"verify error: {e}"}
    accept, score, reason = _parse_verify_json(text)
    if score < _REJECT_THRESHOLD and accept:
        accept = False  # engine-enforced floor
    return {"accept": accept, "score": score, "reason": reason}
