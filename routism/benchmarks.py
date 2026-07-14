"""Simple benchmark API: run NORTHSTAR eval harness and list past results.

Wraps ``routism_orch.eval_conductor`` so the UI can start a run, poll status,
and open historical JSON under ``eval_results/``.
"""
from __future__ import annotations

import json
import re
import threading
import time
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

_REPO = Path(__file__).resolve().parent.parent
_EVAL_DIR = _REPO / "eval_results"
_SEEDS = {
    "northstar": {
        "id": "northstar",
        "name": "NORTHSTAR (hard multi-step)",
        "path": str(_REPO / "routism_orch" / "eval_seed_northstar.json"),
        "description": "Hard multi-deliverable tasks — Conductor vs best solo worker.",
    },
    "full": {
        "id": "full",
        "name": "Full seed suite",
        "path": str(_REPO / "routism_orch" / "eval_seed.json"),
        "description": "Larger multi-step suite (more tasks, longer runs).",
    },
}

router = APIRouter(prefix="/v1/benchmarks", tags=["benchmarks"])

# Single in-process job (one run at a time — eval is heavy).
_lock = threading.Lock()
_job: dict[str, Any] = {
    "id": None,
    "status": "idle",  # idle | running | done | error
    "started_at": None,
    "finished_at": None,
    "params": None,
    "log": [],
    "result_path": None,
    "result": None,
    "error": None,
    "progress": "",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _append_log(msg: str, *, stamp: bool = True) -> None:
    text = (msg or "").rstrip()
    if not text:
        return
    # Split multi-line chunks (eval_conductor prints big tables sometimes)
    for part in text.splitlines():
        part = part.rstrip()
        if not part:
            continue
        line = (
            f"{datetime.now(timezone.utc).strftime('%H:%M:%S')}  {part}"
            if stamp
            else part
        )
        with _lock:
            log = list(_job.get("log") or [])
            log.append(line)
            # Cap log size for API responses (keep more during long runs)
            _job["log"] = log[-800:]
            # Last non-empty line is the "progress" headline
            _job["progress"] = part[:200]


class _LogTee:
    """Capture stdout/stderr from the eval harness into the job log (live UI)."""

    def __init__(self, original, *, also_original: bool = True) -> None:
        self._original = original
        self._also = also_original
        self._buf = ""

    def write(self, data: str) -> int:
        if not isinstance(data, str):
            data = str(data)
        if self._also and self._original is not None:
            try:
                self._original.write(data)
                self._original.flush()
            except Exception:
                pass
        self._buf += data
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            if line.strip():
                _append_log(line, stamp=True)
        return len(data)

    def flush(self) -> None:
        if self._buf.strip():
            _append_log(self._buf, stamp=True)
            self._buf = ""
        if self._also and self._original is not None:
            try:
                self._original.flush()
            except Exception:
                pass

    def isatty(self) -> bool:
        return False


def _safe_name(name: str) -> str:
    base = Path(name).name
    if not re.fullmatch(r"[\w.\-]+\.json", base):
        raise HTTPException(status_code=400, detail="invalid result name")
    return base


def _summarize_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Compact view for the UI (no huge answer texts)."""
    northstar = payload.get("northstar") or {}
    comparison = payload.get("comparison") or {}
    metrics = comparison.get("metrics") or northstar or {}
    rows = comparison.get("rows") or []
    compact_rows = []
    for r in rows:
        cscore = r.get("conductor_score")
        if cscore is None:
            cscore = r.get("conductor")
        max_solo = r.get("max_worker_score")
        if max_solo is None:
            max_solo = r.get("max_solo")
        if max_solo is None:
            max_solo = r.get("max_worker")
        compact_rows.append(
            {
                "task_id": r.get("task_id"),
                "category": r.get("category"),
                "worker_scores": r.get("worker_scores") or r.get("scores") or {},
                "conductor": cscore,
                "conductor_score": cscore,
                "max_solo": max_solo,
                "winner": r.get("winner"),
                "beats_max": r.get("conductor_beats_max_worker"),
                "delta": (
                    (float(cscore) - float(max_solo))
                    if cscore is not None and max_solo is not None
                    else r.get("delta")
                ),
                "models_used": r.get("models_used"),
            }
        )
    summaries = payload.get("summaries") or {}
    mean_scores = {
        k: (v or {}).get("mean_score")
        for k, v in summaries.items()
        if isinstance(v, dict)
    }
    ship = (
        metrics.get("SHIP")
        or northstar.get("SHIP")
        or payload.get("SHIP")
    )
    win_rate = (
        metrics.get("win_rate_vs_max_solo")
        or metrics.get("win_rate")
        or northstar.get("win_rate")
        or payload.get("win_rate")
    )
    mean_delta = (
        metrics.get("mean_delta")
        or northstar.get("mean_delta")
        or payload.get("mean_delta")
    )
    n_tasks = (
        (payload.get("seed") or {}).get("n_tasks")
        or metrics.get("n_tasks")
        or len(compact_rows)
        or 0
    )
    return {
        "kind": payload.get("kind") or payload.get("harness_kind"),
        "created_at": payload.get("created_at") or payload.get("when"),
        "seed": payload.get("seed"),
        "worker_ids": payload.get("worker_ids"),
        "models": payload.get("models"),
        "SHIP": ship,
        "win_rate": win_rate,
        "mean_delta": mean_delta,
        "mean_conductor_score": metrics.get("mean_conductor_score"),
        "mean_max_worker_score": metrics.get("mean_max_worker_score"),
        "metrics": metrics,
        "mean_scores": mean_scores,
        "rows": compact_rows,
        "n_tasks": n_tasks,
    }


class RunRequest(BaseModel):
    seed: str = Field(default="northstar", description="northstar | full")
    mode: str = Field(default="all", description="all | conductor | dry-run")
    limit: int | None = Field(default=4, ge=1, le=50)
    timeout_s: float = Field(default=600.0, ge=30, le=3600)


@router.get("/seeds")
def list_seeds() -> dict:
    out = []
    for s in _SEEDS.values():
        p = Path(s["path"])
        n_tasks = None
        if p.is_file():
            try:
                raw = json.loads(p.read_text(encoding="utf-8"))
                n_tasks = len(raw.get("tasks") or [])
            except Exception:
                n_tasks = None
        out.append({**s, "n_tasks": n_tasks, "exists": p.is_file()})
    return {"seeds": out}


@router.get("/status")
def job_status() -> dict:
    with _lock:
        snap = dict(_job)
    # Don't dump full result answers in status poll — use summary if done
    result = snap.get("result")
    summary = _summarize_payload(result) if isinstance(result, dict) else None
    return {
        "id": snap.get("id"),
        "status": snap.get("status"),
        "started_at": snap.get("started_at"),
        "finished_at": snap.get("finished_at"),
        "params": snap.get("params"),
        "log": snap.get("log") or [],
        "progress": snap.get("progress") or "",
        "result_path": snap.get("result_path"),
        "error": snap.get("error"),
        "summary": summary,
    }


@router.get("/results")
def list_results() -> dict:
    _EVAL_DIR.mkdir(parents=True, exist_ok=True)
    items = []
    for p in sorted(_EVAL_DIR.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
        if p.name.startswith("."):
            continue
        meta: dict[str, Any] = {
            "name": p.name,
            "path": str(p.relative_to(_REPO)),
            "size_bytes": p.stat().st_size,
            "mtime": datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc).isoformat(),
        }
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                s = _summarize_payload(raw)
                meta["SHIP"] = s.get("SHIP")
                meta["win_rate"] = s.get("win_rate")
                meta["mean_delta"] = s.get("mean_delta")
                meta["kind"] = s.get("kind")
                meta["n_tasks"] = s.get("n_tasks")
                meta["worker_ids"] = s.get("worker_ids")
        except Exception:
            pass
        items.append(meta)
    return {"results": items[:50]}


@router.get("/results/{name}")
def get_result(name: str) -> dict:
    base = _safe_name(name)
    p = _EVAL_DIR / base
    if not p.is_file():
        raise HTTPException(status_code=404, detail=f"result {base!r} not found")
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"invalid json: {e}") from e
    if not isinstance(raw, dict):
        raise HTTPException(status_code=500, detail="result is not an object")
    return {
        "name": base,
        "path": str(p.relative_to(_REPO)),
        "summary": _summarize_payload(raw),
        # Full payload for advanced inspection (may be large)
        "payload": raw,
    }


def _run_job(job_id: str, req: RunRequest) -> None:
    import sys

    # Tee eval harness prints into the job log so the UI can poll them live.
    old_out, old_err = sys.stdout, sys.stderr
    tee_out = _LogTee(old_out, also_original=True)
    tee_err = _LogTee(old_err, also_original=True)
    sys.stdout = tee_out  # type: ignore[assignment]
    sys.stderr = tee_err  # type: ignore[assignment]
    try:
        from routism_orch.eval_conductor import (
            load_seed,
            run_dry,
            run_live,
            write_results,
            validate_seed,
        )

        seed_meta = _SEEDS.get(req.seed) or _SEEDS["northstar"]
        seed_path = Path(seed_meta["path"])
        _append_log(f"Validating seed {seed_path.name}…")
        validate_seed(seed_path)
        tasks = load_seed(seed_path)
        if req.limit is not None:
            tasks = tasks[: int(req.limit)]
        _append_log(f"Tasks: {len(tasks)} — {[t.id for t in tasks]}")

        workers_path = _REPO / "routism.yaml"
        mode = (req.mode or "all").strip().lower()

        if mode in ("dry-run", "dry_run", "dry"):
            _append_log("Running dry-run (plan structure only, no live APIs)…")
            payload = run_dry(tasks)
            kind = "ui_dry"
        else:
            live_mode = mode if mode in ("all", "conductor", "parallel", "single_worker") else "all"
            _append_log(
                f"Live mode={live_mode} timeout={req.timeout_s}s "
                f"workers={workers_path} — this can take a while…"
            )
            _append_log(
                "Live logs stream below (per task / solo worker / Conductor)…"
            )
            payload = run_live(
                tasks,
                mode=live_mode,
                worker_id=None,
                workers_path=workers_path,
                timeout_s=float(req.timeout_s),
            )
            kind = f"ui_{live_mode}"

        tee_out.flush()
        tee_err.flush()
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out = _EVAL_DIR / f"ui_{req.seed}_{mode.replace('-', '_')}_{ts}.json"
        _EVAL_DIR.mkdir(parents=True, exist_ok=True)
        path = write_results(payload, out)
        _append_log(f"Wrote {path}")

        with _lock:
            if _job.get("id") == job_id:
                _job["status"] = "done"
                _job["finished_at"] = _now_iso()
                _job["result_path"] = str(Path(path).relative_to(_REPO))
                _job["result"] = payload if isinstance(payload, dict) else None
                _job["progress"] = "Complete"
                _job["error"] = None
    except Exception as e:  # noqa: BLE001
        tb = traceback.format_exc()
        _append_log(f"ERROR: {type(e).__name__}: {e}")
        with _lock:
            if _job.get("id") == job_id:
                _job["status"] = "error"
                _job["finished_at"] = _now_iso()
                _job["error"] = f"{type(e).__name__}: {e}"
                _job["progress"] = "Failed"
                log = list(_job.get("log") or [])
                for part in tb.strip().splitlines()[-12:]:
                    log.append(part)
                _job["log"] = log[-800:]
    finally:
        try:
            tee_out.flush()
            tee_err.flush()
        except Exception:
            pass
        sys.stdout = old_out
        sys.stderr = old_err


@router.post("/run")
def start_run(body: RunRequest) -> dict:
    with _lock:
        if _job.get("status") == "running":
            raise HTTPException(
                status_code=409,
                detail="a benchmark is already running — wait for it to finish",
            )
        job_id = uuid.uuid4().hex[:12]
        _job.update(
            {
                "id": job_id,
                "status": "running",
                "started_at": _now_iso(),
                "finished_at": None,
                "params": body.model_dump(),
                "log": [],
                "result_path": None,
                "result": None,
                "error": None,
                "progress": "Starting…",
            }
        )

    t = threading.Thread(
        target=_run_job,
        args=(job_id, body),
        name=f"benchmark-{job_id}",
        daemon=True,
    )
    t.start()
    return {"ok": True, "id": job_id, "status": "running"}


@router.post("/cancel")
def cancel_hint() -> dict:
    """Eval runs are not safely interruptible mid-call; document state only."""
    with _lock:
        st = _job.get("status")
    return {
        "ok": False,
        "status": st,
        "message": (
            "In-flight worker HTTP calls cannot be force-cancelled safely. "
            "Wait for the current job to finish, or restart the API process."
        ),
    }
