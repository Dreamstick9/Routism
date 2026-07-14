"""Frozen NORTHSTAR ship math — pure, no side effects, no score injection.

Ship gate (strict):
  win_rate = fraction of tasks where conductor_score > max_solo_score
  ship = win_rate >= 0.70 and mean_delta >= 0.3

Scores are absolute multi-part 0–10 (coverage + structure + richness).
No pairwise max_solo+1.0, no team_bonus, ties are not wins.
"""
from __future__ import annotations

import math
import re
from typing import Any


def split_deliverables(query: str) -> list[str]:
    """Split a multi-part user query into concrete deliverable clauses."""
    q = (query or "").strip()
    if not q:
        return []
    verb = (
        r"(?:design|implement|write|list|compare|recommend|sketch|explain|"
        r"summarize|propose|draft|analyze|create|build|add)"
    )
    parts = re.split(
        rf"(?:,\s*|\s+and\s+|\s+then\s+|;+\s*)(?={verb}\b)",
        q,
        flags=re.IGNORECASE,
    )
    parts = [p.strip(" .") for p in parts if p and len(p.strip()) > 10]
    if len(parts) < 2:
        return [q]
    return parts[:8]


def part_kind(part: str) -> str:
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


def score_part_absolute(part: str, answer: str) -> float:
    """Absolute 0–10 for one deliverable from answer text."""
    ans = answer or ""
    if not ans.strip():
        return 0.0
    kind = part_kind(part)
    low_ans = ans.lower()
    tokens = [
        t
        for t in re.findall(r"[a-zA-Z]{4,}", (part or "").lower())
        if t
        not in {
            "with", "that", "this", "from", "into", "then", "write", "list",
            "three", "four", "each", "have", "when", "using", "without",
            "implement", "design", "python", "function",
        }
    ]
    tokens = list(dict.fromkeys(tokens))[:14]
    cov = (sum(1 for t in tokens if t in low_ans) / len(tokens)) if tokens else 0.55
    score = 3.0 + 5.5 * cov

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
        if re.search(r"(?m)^#{1,3}\s+|^\|", ans):
            score += 1.0
        if cov >= 0.5:
            score = max(score, 7.0)

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

    if kind in ("code", "tests") and len(ans) < 400:
        score = min(score, 6.0)

    return round(max(0.0, min(10.0, score)), 3)


def score_answer_absolute(answer: str, query: str) -> dict[str, Any]:
    """Primary NORTHSTAR absolute multi-part score 0–10 (deterministic, pure).

    No LLM calls, no synthetic margins. Applied identically to Conductor and solos.
    """
    ans = (answer or "").strip()
    if not ans or "no successful subtask" in ans.lower():
        return {
            "verifier_score": 0.0,
            "verifier_reason": "empty or failed assembly",
            "passed": False,
            "part_scores": [],
            "deliverables": [],
            "score_method": "absolute_multipart_0_10",
            "synthetic_margin": False,
        }

    parts = split_deliverables(query)
    part_scores = [score_part_absolute(p, ans) for p in parts]
    det_mean = sum(part_scores) / len(part_scores) if part_scores else 0.0

    headings = len(re.findall(r"(?m)^#{1,3}\s+\S+", ans))
    fences = len(re.findall(r"```", ans)) // 2
    n_defs = len(re.findall(r"\bdef\s+\w+", ans))
    n_asserts = len(re.findall(r"\bassert\b", ans, re.I))
    n_parts = max(1, len(parts))
    h_ratio = min(1.5, headings / float(n_parts))
    structure = min(10.0, 6.0 * h_ratio + min(4.0, fences * 1.2))
    raw_rich = (
        headings * 0.12
        + fences * 1.0
        + n_defs * 0.55
        + n_asserts * 0.35
        + min(3.0, len(ans) / 5000.0)
    )
    richness = 10.0 * (1.0 - math.exp(-raw_rich / 12.0))

    if len(parts) >= 2:
        vs = 0.68 * det_mean + 0.16 * structure + 0.16 * richness
    else:
        vs = det_mean

    if len(parts) >= 3 and headings < 2:
        vs = min(vs, 7.0)
    elif len(parts) >= 4 and headings < 3:
        vs = min(vs, 8.2)

    vs = max(0.0, min(10.0, vs))
    return {
        "verifier_score": round(vs, 3),
        "verifier_reason": (
            f"absolute multipart det={det_mean:.2f} structure={structure:.2f} "
            f"richness={richness:.2f} parts={part_scores}"
        ),
        "passed": vs >= 6.0,
        "part_scores": part_scores,
        "deliverables": parts,
        "structure_score": round(structure, 3),
        "richness_score": round(richness if len(parts) >= 2 else 0.0, 3),
        "det_mean": round(det_mean, 3),
        "score_method": "absolute_multipart_0_10",
        "synthetic_margin": False,
    }


def row_beats_max(conductor_score: float, max_worker_score: float) -> bool:
    """Strict beat: conductor > max solo (ties do NOT count)."""
    return float(conductor_score) > float(max_worker_score) + 1e-9


def compute_ship_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate NORTHSTAR ship metrics from comparison rows.

    Required row keys: conductor_score, max_worker_score, conductor_beats_max_worker
    (beats_max may be recomputed strictly if missing).
    """
    n = len(rows)
    if n == 0:
        return {
            "n_tasks": 0,
            "conductor_beats_max_worker_count": 0,
            "conductor_beats_max_worker_rate": 0.0,
            "mean_conductor_score": 0.0,
            "mean_max_worker_score": 0.0,
            "mean_delta": 0.0,
            "win_rate_vs_max_solo": 0.0,
            "score_scale": "0-10_absolute_multipart",
            "SHIP": "NO",
            "ship_yes": False,
            "synthetic_margin": False,
            "strict_beat": True,
        }

    # Recompute strict beats from scores (never trust injected flags alone)
    beat_max = 0
    for r in rows:
        c = float(r["conductor_score"])
        mx = float(r["max_worker_score"])
        if row_beats_max(c, mx):
            beat_max += 1
            r["conductor_beats_max_worker"] = True
            r["conductor_ties_max_worker"] = False
        else:
            r["conductor_beats_max_worker"] = False
            r["conductor_ties_max_worker"] = abs(c - mx) < 1e-9 and c > 0

    mean_c = sum(float(r["conductor_score"]) for r in rows) / n
    mean_max = sum(float(r["max_worker_score"]) for r in rows) / n
    mean_delta = mean_c - mean_max
    win_rate = beat_max / n
    ship = win_rate >= 0.70 and mean_delta >= 0.3

    beat_every = sum(1 for r in rows if r.get("conductor_beats_every_worker"))
    tie_max = sum(1 for r in rows if r.get("conductor_ties_max_worker"))
    cond_wins = sum(1 for r in rows if r.get("winner") == "conductor")
    par_wins = sum(1 for r in rows if r.get("winner") == "parallel")
    worker_wins = sum(1 for r in rows if str(r.get("winner", "")).startswith("worker:"))

    return {
        "n_tasks": n,
        "conductor_beats_every_worker_count": beat_every,
        "conductor_beats_every_worker_rate": round(beat_every / n, 3),
        "conductor_beats_max_worker_count": beat_max,
        "conductor_beats_max_worker_rate": round(win_rate, 3),
        "conductor_ties_max_worker_count": tie_max,
        "conductor_wins_count": cond_wins,
        "conductor_wins_rate": round(cond_wins / n, 3),
        "parallel_wins_count": par_wins,
        "worker_wins_count": worker_wins,
        "mean_conductor_score": round(mean_c, 3),
        "mean_parallel_score": round(
            sum(float(r.get("parallel_score") or 0) for r in rows) / n, 3
        ),
        "mean_max_worker_score": round(mean_max, 3),
        "mean_delta": round(mean_delta, 3),
        "win_rate_vs_max_solo": round(win_rate, 3),
        "score_scale": "0-10_absolute_multipart",
        "SHIP": "YES" if ship else "NO",
        "ship_yes": ship,
        "synthetic_margin": False,
        "strict_beat": True,
    }


def assert_no_offline_recovery_marker(answer: str) -> bool:
    """True if answer is free of offline-only recovery markers.

    Product-path recovery uses score_reason=recovery_fill events, not this marker.
    """
    return "## Recovery fill-in" not in (answer or "")
