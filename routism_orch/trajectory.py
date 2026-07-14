"""Best-effort trajectory logging for Conductor runs.

Appends one JSON object per completed run to::

    data/trajectories/YYYYMMDD.jsonl

Enabled when ``CONDUCTOR_LOG_TRAJECTORIES=1`` (default **on** so we collect
data for offline eval / future GRPO). Set ``0`` / ``false`` / ``off`` to disable.

Never raises into the hot path — every public function fails open.
"""
from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_lock = threading.Lock()

# Last successful log (for GET /v1/metrics). Process-local only.
_last_models_used: list[str] = []
_last_run_id: str | None = None
_last_logged_at: float | None = None


def trajectories_enabled() -> bool:
    """CONDUCTOR_LOG_TRAJECTORIES default ON. Set 0/false/off to disable."""
    v = os.environ.get("CONDUCTOR_LOG_TRAJECTORIES", "1").strip().lower()
    return v not in ("0", "false", "no", "off")


def trajectories_dir() -> Path:
    """Repo-root ``data/trajectories`` (override with ROUTISM_TRAJECTORIES_DIR)."""
    override = os.environ.get("ROUTISM_TRAJECTORIES_DIR", "").strip()
    if override:
        return Path(override)
    # routism_orch/trajectory.py → repo root
    return Path(__file__).resolve().parent.parent / "data" / "trajectories"


def last_models_used() -> list[str]:
    """Worker ids from the most recently logged trajectory (may be empty)."""
    with _lock:
        return list(_last_models_used)


def last_trajectory_meta() -> dict[str, Any]:
    """Snapshot for metrics dashboards."""
    with _lock:
        return {
            "models_used": list(_last_models_used),
            "run_id": _last_run_id,
            "logged_at": _last_logged_at,
            "enabled": trajectories_enabled(),
        }


def _safe_jsonable(obj: Any, *, depth: int = 0) -> Any:
    """Coerce common types to JSON-serializable form; drop huge blobs."""
    if depth > 8:
        return str(type(obj).__name__)
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj
    if isinstance(obj, Path):
        return str(obj)
    if isinstance(obj, dict):
        out: dict[str, Any] = {}
        for k, v in list(obj.items())[:64]:
            out[str(k)] = _safe_jsonable(v, depth=depth + 1)
        return out
    if isinstance(obj, (list, tuple)):
        return [_safe_jsonable(x, depth=depth + 1) for x in list(obj)[:128]]
    if hasattr(obj, "to_dict") and callable(obj.to_dict):
        try:
            return _safe_jsonable(obj.to_dict(), depth=depth + 1)
        except Exception:
            return str(obj)
    # CandidateScore / dataclasses-like
    if hasattr(obj, "__dict__"):
        try:
            return _safe_jsonable(vars(obj), depth=depth + 1)
        except Exception:
            pass
    return str(obj)


def _normalize_scores(scores: Any) -> list[dict[str, Any]]:
    if not scores:
        return []
    out: list[dict[str, Any]] = []
    if isinstance(scores, dict):
        scores = list(scores.values())
    for s in scores:
        if s is None:
            continue
        if isinstance(s, dict):
            out.append({
                "worker_id": s.get("worker_id"),
                "score": s.get("score"),
                "reason": s.get("reason") or s.get("score_reason") or "",
                "role": s.get("role"),
            })
            continue
        out.append({
            "worker_id": getattr(s, "worker_id", None),
            "score": getattr(s, "score", None),
            "reason": getattr(s, "reason", "") or getattr(s, "score_reason", "") or "",
            "role": getattr(s, "role", None),
        })
    return out


def log_trajectory(
    run_id: str,
    query: str,
    plan_dict: dict | None,
    events_summary: list | dict | None,
    final_answer: str | None,
    scores: Any,
    models_used: list[str] | set[str] | None,
    win_vs_best: float | None = None,
    **extra: Any,
) -> Path | None:
    """Append one trajectory record to today's JSONL file.

    Returns the path written, or None if disabled / on failure.
    Best-effort: never raises.
    """
    try:
        if not trajectories_enabled():
            return None

        models_list = sorted({str(m) for m in (models_used or []) if m})
        # Cap answer length so a runaway model does not fill the disk.
        answer = final_answer if final_answer is not None else ""
        if len(answer) > 50_000:
            answer = answer[:50_000] + "…[truncated]"

        record: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "ts_unix": time.time(),
            "run_id": str(run_id or ""),
            "query": (query or "")[:8_000],
            "plan": _safe_jsonable(plan_dict or {}),
            "events_summary": _safe_jsonable(events_summary or []),
            "final_answer": answer,
            "scores": _normalize_scores(scores),
            "models_used": models_list,
            "win_vs_best": win_vs_best,
        }
        for k, v in extra.items():
            if k not in record:
                record[k] = _safe_jsonable(v)

        day = datetime.now(timezone.utc).strftime("%Y%m%d")
        d = trajectories_dir()
        d.mkdir(parents=True, exist_ok=True)
        path = d / f"{day}.jsonl"
        line = json.dumps(record, ensure_ascii=False, default=str) + "\n"

        with _lock:
            with path.open("a", encoding="utf-8") as f:
                f.write(line)
            global _last_models_used, _last_run_id, _last_logged_at
            _last_models_used = models_list
            _last_run_id = str(run_id or "") or None
            _last_logged_at = time.time()

        return path
    except Exception:
        return None


def summarize_events(events: list[dict]) -> list[dict[str, Any]]:
    """Compact event list for logging (no full answer bodies)."""
    out: list[dict[str, Any]] = []
    try:
        for ev in events or []:
            if not isinstance(ev, dict):
                continue
            kind = ev.get("_event") or ev.get("event") or "unknown"
            row: dict[str, Any] = {"event": kind}
            if kind == "meta":
                row["degraded"] = ev.get("degraded")
                row["orchestration"] = ev.get("orchestration")
                row["degraded_reason"] = ev.get("degraded_reason")
            elif kind == "conductor_plan":
                row["layers"] = ev.get("layers")
                row["subtasks"] = ev.get("subtasks")
            elif kind == "dag_layer_start":
                row["layer"] = ev.get("layer")
                row["subtask_ids"] = ev.get("subtask_ids")
            elif kind == "dag_layer_complete":
                row["layer"] = ev.get("layer")
                row["elapsed_ms"] = ev.get("elapsed_ms")
            elif kind == "scores":
                cands = ev.get("candidates") or ev.get("scores") or []
                if isinstance(cands, list):
                    row["n"] = len(cands)
                    row["top"] = [
                        {
                            "worker_id": c.get("worker_id") if isinstance(c, dict) else None,
                            "score": c.get("score") if isinstance(c, dict) else None,
                        }
                        for c in cands[:8]
                        if isinstance(c, dict)
                    ]
            elif kind == "k_sample_pick":
                row["subtask_id"] = ev.get("subtask_id")
                row["winner"] = ev.get("winner")
                row["method"] = ev.get("method")
            elif kind == "synthesis":
                row["strategy"] = ev.get("strategy")
                row["engine"] = ev.get("engine")
            elif kind == "done":
                row["degraded"] = ev.get("degraded")
                row["partial_success"] = ev.get("partial_success")
                ans = ev.get("answer") or ""
                row["answer_len"] = len(ans) if isinstance(ans, str) else 0
                cond = (ev.get("parallel") or {}).get("conductor") or {}
                if cond:
                    row["models_used"] = cond.get("models_used")
            elif kind == "step":
                row["worker_id"] = ev.get("worker_id")
                row["ok"] = not bool(ev.get("error"))
            elif kind == "error":
                row["message"] = str(ev.get("message") or ev.get("error") or "")[:500]
            out.append(row)
            if len(out) >= 200:
                out.append({"event": "_truncated", "n": len(events)})
                break
    except Exception:
        pass
    return out
