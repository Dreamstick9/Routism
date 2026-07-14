"""PR-3 — CapabilityAssigner v2 (unit-normalized health-aware scoring).

Score formula (all unitless terms):

    score = α·tag_overlap + β·health + γ_eff·win_rate − δ·latency_penalty − ε·load

Flag: CONDUCTOR_ASSIGN_V2=1 enables this path (default **off** until eval).
When off, callers keep legacy least-used + soft tags in conductor.py.

Health snapshot is once-per-run (wall budget 2s, cache 30s). WorkerStats is
process-local EMA only (disk = PR-9).
"""
from __future__ import annotations

import asyncio
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Iterable, Protocol

import httpx

# Meta tags = hosting/billing, not capability affinity.
META_TAGS = frozenset({"cloud", "free", "local", "ollama", "paid", "fast"})


def assign_v2_enabled() -> bool:
    """CONDUCTOR_ASSIGN_V2 default ON (prod quality path). Set 0 to force legacy."""
    v = os.environ.get("CONDUCTOR_ASSIGN_V2", "1").strip().lower()
    return v not in ("0", "false", "no", "off")


def quality_band() -> float:
    """Workers within (best − band) are eligible; then prefer least-used (anti-drain)."""
    try:
        return max(0.0, float(os.environ.get("CONDUCTOR_QUALITY_BAND", "0.4")))
    except ValueError:
        return 0.4


def max_share() -> float:
    """Max fraction of plan nodes one worker may take (unless no alternative)."""
    try:
        return min(1.0, max(0.1, float(os.environ.get("CONDUCTOR_MAX_SHARE", "0.5"))))
    except ValueError:
        return 0.5


@dataclass(frozen=True)
class AssignWeights:
    alpha: float = 1.0   # tag_overlap
    beta: float = 5.0    # health
    gamma: float = 2.0   # win_rate (scaled by γ_eff)
    delta: float = 0.5   # latency_penalty
    epsilon: float = 0.3 # load
    n_min: int = 5
    ema_win: float = 0.2
    ema_lat: float = 0.2


DEFAULT_WEIGHTS = AssignWeights()


@dataclass
class WorkerStat:
    wins_ema: float = 0.5  # prior when n=0
    n: int = 0
    latency_ema: float | None = None  # ms; None until first success


class WorkerStats:
    """Process-local singleton (module-level). P1 PR-9: snapshot to disk."""

    def __init__(self) -> None:
        self.by_id: dict[str, WorkerStat] = {}
        self._lock = threading.Lock()

    def get(self, worker_id: str) -> WorkerStat:
        with self._lock:
            st = self.by_id.get(worker_id)
            if st is None:
                st = WorkerStat()
                self.by_id[worker_id] = st
            return st

    def pool_median_latency(self, worker_ids: Iterable[str]) -> float | None:
        """Median of non-None latency_ema over worker_ids; None if no samples."""
        with self._lock:
            vals = sorted(
                self.by_id[w].latency_ema
                for w in worker_ids
                if w in self.by_id and self.by_id[w].latency_ema is not None
            )
        if not vals:
            return None
        if len(vals) == 1:
            return vals[0]
        mid = len(vals) // 2
        if len(vals) % 2 == 1:
            return float(vals[mid])
        return (vals[mid - 1] + vals[mid]) / 2.0

    def record_outcome(
        self,
        worker_id: str,
        *,
        score_0_10: float,
        latency_ms: float | None,
        weights: AssignWeights = DEFAULT_WEIGHTS,
    ) -> None:
        """Update EMA after an absolute verifier score on a successful sample."""
        score = max(0.0, min(10.0, float(score_0_10)))
        with self._lock:
            st = self.by_id.get(worker_id)
            if st is None:
                st = WorkerStat()
                self.by_id[worker_id] = st
            a = weights.ema_win
            st.wins_ema = (1.0 - a) * st.wins_ema + a * (score / 10.0)
            st.n += 1
            if latency_ms is not None and latency_ms >= 0:
                al = weights.ema_lat
                if st.latency_ema is None:
                    st.latency_ema = float(latency_ms)
                else:
                    st.latency_ema = (1.0 - al) * st.latency_ema + al * float(latency_ms)


# Process singleton
_WORKER_STATS = WorkerStats()


def get_worker_stats() -> WorkerStats:
    return _WORKER_STATS


def reset_worker_stats_for_tests() -> None:
    """Test helper — clear process EMA state."""
    global _WORKER_STATS
    _WORKER_STATS = WorkerStats()


def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def tag_overlap(subtask_tags: list[str] | None, worker_tags: list[str] | None) -> float:
    stags = set(subtask_tags or ()) - META_TAGS
    wtags = set(worker_tags or ()) - META_TAGS
    if not stags:
        return 0.0
    return len(stags & wtags) / max(1, len(stags))


def latency_penalty(lat_ema: float | None, pool_median: float | None) -> float:
    """Unit-normalized latency vs pool median. None lat or median → 0."""
    if lat_ema is None or pool_median is None:
        return 0.0
    return clamp((lat_ema - pool_median) / max(pool_median, 1.0), -1.0, 2.0)


def gamma_eff(n: int, weights: AssignWeights = DEFAULT_WEIGHTS) -> float:
    return weights.gamma * min(1.0, n / max(1, weights.n_min))


def score_worker(
    *,
    worker_id: str,
    subtask_tags: list[str] | None,
    worker_tags: list[str] | None,
    health: float,
    wins_ema: float,
    n: int,
    lat_ema: float | None,
    pool_median: float | None,
    load: float,
    weights: AssignWeights = DEFAULT_WEIGHTS,
) -> float:
    """Unit-normalized assign score (worked-example oracle target)."""
    tov = tag_overlap(subtask_tags, worker_tags)
    ge = gamma_eff(n, weights)
    win = clamp(wins_ema, 0.0, 1.0)
    lat_pen = latency_penalty(lat_ema, pool_median)
    load_c = clamp(load, 0.0, 1.0)
    h = 1.0 if health else 0.0
    return (
        weights.alpha * tov
        + weights.beta * h
        + ge * win
        - weights.delta * lat_pen
        - weights.epsilon * load_c
    )


def _load_factor(usage: dict[str, int], worker_id: str) -> float:
    if not usage:
        return 0.0
    mx = max(usage.values()) if usage else 0
    mx = max(1, mx)
    return usage.get(worker_id, 0) / mx


def rank_workers(
    subtask_tags: list[str] | None,
    worker_tags: dict[str, list[str]],
    *,
    health: dict[str, bool] | None = None,
    stats: WorkerStats | None = None,
    usage: dict[str, int] | None = None,
    weights: AssignWeights = DEFAULT_WEIGHTS,
) -> tuple[list[str], dict[str, float], str | None]:
    """Rank workers by score_worker descending.

    Returns (ranked_ids, scores_by_id, degraded_reason).
    Unhealthy workers are excluded unless ALL are unhealthy (then all eligible
    with health treated as 0 and degraded_reason=all_workers_unhealthy).
    """
    stats = stats or get_worker_stats()
    usage = usage or {w: 0 for w in worker_tags}
    health = health if health is not None else {w: True for w in worker_tags}

    all_ids = list(worker_tags.keys())
    if not all_ids:
        return [], {}, None

    healthy = [w for w in all_ids if health.get(w, True)]
    degraded_reason: str | None = None
    if not healthy:
        eligible = list(all_ids)
        degraded_reason = "all_workers_unhealthy"
        health_for_score = {w: False for w in eligible}
    else:
        eligible = healthy
        health_for_score = {w: True for w in eligible}

    median = stats.pool_median_latency(all_ids)
    scores: dict[str, float] = {}
    for wid in eligible:
        st = stats.get(wid)
        scores[wid] = score_worker(
            worker_id=wid,
            subtask_tags=subtask_tags,
            worker_tags=worker_tags.get(wid),
            health=1.0 if health_for_score.get(wid) else 0.0,
            wins_ema=st.wins_ema,
            n=st.n,
            lat_ema=st.latency_ema,
            pool_median=median,
            load=_load_factor(usage, wid),
            weights=weights,
        )

    ranked = sorted(eligible, key=lambda w: (-scores[w], w))
    return ranked, scores, degraded_reason


def pick_worker_v2(
    subtask_tags: list[str] | None,
    worker_tags: dict[str, list[str]],
    *,
    health: dict[str, bool] | None = None,
    stats: WorkerStats | None = None,
    usage: dict[str, int] | None = None,
    weights: AssignWeights = DEFAULT_WEIGHTS,
) -> tuple[str | None, str, float | None]:
    """Pick top worker; return (worker_id, assignment_reason, score)."""
    ranked, scores, degraded = rank_workers(
        subtask_tags,
        worker_tags,
        health=health,
        stats=stats,
        usage=usage,
        weights=weights,
    )
    if not ranked:
        return None, "assign_v2:empty_pool", None
    top = ranked[0]
    reason_bits = [f"assign_v2 score={scores[top]:.3f}"]
    if degraded:
        reason_bits.append(degraded)
    # short human-readable why
    tov = tag_overlap(subtask_tags, worker_tags.get(top))
    reason_bits.append(f"tag_ov={tov:.2f}")
    return top, "; ".join(reason_bits), scores[top]


# ---------------------------------------------------------------------------
# Health snapshot (once per run, wall budget 2s, cache 30s)
# ---------------------------------------------------------------------------


class _WorkerLike(Protocol):
    id: str
    base_url: str

    @property
    def api_key(self) -> str | None: ...


_health_cache: dict[str, tuple[float, bool]] = {}
_health_cache_lock = threading.Lock()
_HEALTH_CACHE_TTL = 30.0


def _probe_one(worker: Any, timeout: float) -> bool:
    """GET /v1/models reachability — same 2xx-only rule as management health probe."""
    from routism.health_probe import is_healthy_status, models_probe_url

    base = (getattr(worker, "base_url", None) or "").rstrip("/")
    if not base:
        return False
    url = models_probe_url(base)
    headers: dict[str, str] = {}
    key = getattr(worker, "api_key", None)
    if key:
        try:
            from routism.crypto_keys import resolve_api_key

            key = resolve_api_key(key)
        except Exception:
            pass  # fall through with raw key / skip auth if decrypt fails
        if key:
            headers["Authorization"] = f"Bearer {key}"
    try:
        with httpx.Client(timeout=timeout) as client:
            r = client.get(url, headers=headers)
        return is_healthy_status(r.status_code)
    except Exception:
        return False


def snapshot_worker_health(
    workers: list[Any],
    *,
    wall_budget_s: float = 2.0,
    cache_ttl_s: float = _HEALTH_CACHE_TTL,
) -> dict[str, bool]:
    """Sync health map for assign. On timeout/error → False (health=0). Fail-open cache."""
    now = time.monotonic()
    result: dict[str, bool] = {}
    to_probe: list[Any] = []

    with _health_cache_lock:
        for w in workers:
            wid = getattr(w, "id", None)
            if not wid:
                continue
            cached = _health_cache.get(wid)
            if cached and (now - cached[0]) <= cache_ttl_s:
                result[wid] = cached[1]
            else:
                to_probe.append(w)

    if not to_probe:
        return result

    # Per-worker timeout shares the wall budget.
    n = len(to_probe)
    per = max(0.15, min(2.0, wall_budget_s / n))
    deadline = now + wall_budget_s

    for w in to_probe:
        wid = w.id
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            result[wid] = False
            with _health_cache_lock:
                _health_cache[wid] = (time.monotonic(), False)
            continue
        ok = _probe_one(w, timeout=min(per, remaining))
        result[wid] = ok
        with _health_cache_lock:
            _health_cache[wid] = (time.monotonic(), ok)

    # Include workers that were fully cache hits already
    for w in workers:
        wid = getattr(w, "id", None)
        if wid and wid not in result:
            result[wid] = False
    return result


async def snapshot_worker_health_async(
    workers: list[Any],
    *,
    wall_budget_s: float = 2.0,
    cache_ttl_s: float = _HEALTH_CACHE_TTL,
) -> dict[str, bool]:
    """Async wrapper — runs sync probes in a thread (httpx sync client)."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        lambda: snapshot_worker_health(
            workers, wall_budget_s=wall_budget_s, cache_ttl_s=cache_ttl_s
        ),
    )


def clear_health_cache_for_tests() -> None:
    with _health_cache_lock:
        _health_cache.clear()


# ---------------------------------------------------------------------------
# PR-4 — k-sample assign
# ---------------------------------------------------------------------------


def k_sample_enabled() -> bool:
    """CONDUCTOR_K_SAMPLE default ON (critical dual-sample). Set 0 to disable."""
    v = os.environ.get("CONDUCTOR_K_SAMPLE", "1").strip().lower()
    return v not in ("0", "false", "no", "off")


def assign_k(
    subtask_tags: list[str] | None,
    worker_tags: dict[str, list[str]],
    *,
    k: int = 1,
    health: dict[str, bool] | None = None,
    stats: WorkerStats | None = None,
    usage: dict[str, int] | None = None,
    assign_v2: bool | None = None,
    plan_size: int | None = None,
) -> tuple[list[str], str]:
    """Pick up to k distinct workers for a node.

    Ranking backend:
      * assign_v2 True  → unit-normalized score_worker + quality band + max share
      * assign_v2 False → legacy least-used + soft tag bonus

    Quality band: only workers within (best − CONDUCTOR_QUALITY_BAND) of the top
    score are eligible; among them prefer least-used (pump the pool, anti-drain).
    Max share: skip workers already over CONDUCTOR_MAX_SHARE of plan_size nodes.

    Returns (picks, assignment_reason). Mutates usage for each pick.
    """
    if assign_v2 is None:
        assign_v2 = assign_v2_enabled()
    usage = usage if usage is not None else {w: 0 for w in worker_tags}
    if not worker_tags:
        return [], "empty_pool"

    k_eff = max(1, int(k))
    n_plan = max(1, int(plan_size) if plan_size else max(len(worker_tags), sum(usage.values()) + k_eff))
    share_cap = max_share()
    max_nodes = max(1, int(share_cap * n_plan + 1e-9))

    if assign_v2:
        ranked, scores, degraded = rank_workers(
            subtask_tags,
            worker_tags,
            health=health,
            stats=stats or get_worker_stats(),
            usage=usage,
        )
        if not ranked:
            return [], "assign_v2:empty"
        best_s = scores[ranked[0]]
        band = quality_band()
        in_band = [w for w in ranked if scores[w] >= best_s - band]
        if not in_band:
            in_band = list(ranked)

        picks: list[str] = []
        for _ in range(min(k_eff, len(in_band))):
            candidates = [w for w in in_band if w not in picks]
            under_cap = [w for w in candidates if usage.get(w, 0) < max_nodes]
            pool = under_cap if under_cap else candidates
            if not pool:
                break
            # Among eligible: least-used, then higher score, then stable id
            pool.sort(key=lambda w: (usage.get(w, 0), -scores.get(w, 0.0), w))
            pick = pool[0]
            picks.append(pick)
            usage[pick] = usage.get(pick, 0) + 1

        reason = (
            f"assign_v2 band={band:.2f} max_share={share_cap:.2f} k={len(picks)} "
            + ",".join(f"{p}:{scores[p]:.2f}" for p in picks)
        )
        if degraded:
            reason += f"; {degraded}"
        return picks, reason

    # Legacy least-used + soft tags (same key as match_subtask_to_worker)
    stags = set(subtask_tags or ()) - META_TAGS
    health = health if health is not None else {w: True for w in worker_tags}
    healthy = [w for w in worker_tags if health.get(w, True)]
    eligible = healthy if healthy else list(worker_tags.keys())

    def _key(worker_id: str) -> tuple:
        wtags = set(worker_tags.get(worker_id) or ()) - META_TAGS
        soft_bonus = len(stags & wtags)
        return (usage.get(worker_id, 0), -soft_bonus, worker_id)

    ranked = sorted(eligible, key=_key)
    picks = ranked[: min(k_eff, len(ranked))]
    for p in picks:
        usage[p] = usage.get(p, 0) + 1
    return picks, f"legacy_least_used k={len(picks)}"
