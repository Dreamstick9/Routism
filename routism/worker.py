"""P0.B — uniform worker connector (httpx) with timeout + cost guards.

A worker is treated as a black box (original arch §9.2): any OpenAI-compatible
/v1/chat/completions endpoint, cloud OR local. The connector only cares about
the request/response contract.

Per-worker in-flight limit
--------------------------
``ROUTISM_WORKER_MAX_INFLIGHT`` (default ``2``) caps how many concurrent jobs
may hit the same ``worker_id`` at once across ``complete`` / ``complete_full``
/ ``fan_out`` (and the async twins). Process-wide module dict of
``asyncio.Semaphore`` values — shared by concurrent tasks on the same event
loop (e.g. concurrent ``/v1/run`` SSE streams on the app loop). Sync callers
take a slot via a private event loop when none is running, so they honor the
same budget.

Optional metric: module global ``inflight_waits`` counts how many times a
caller blocked waiting for a per-worker slot.
"""
from __future__ import annotations

import asyncio
import os
import threading
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass

import httpx

from .config import Worker
from .crypto_keys import resolve_api_key
from .host_reach import rewrite_loopback_url_for_container


class WorkerError(Exception):
    """Raised when a worker call fails: timeout, HTTP error, or bad shape.

    The caller (executor) must catch this and NEVER hang the request thread.
    """


# ---------------------------------------------------------------------------
# Per-worker in-flight semaphore (process-wide, shared event loop)
# ---------------------------------------------------------------------------
# ROUTISM_WORKER_MAX_INFLIGHT (default 2): max concurrent HTTP jobs per
# worker_id. Acquire before each complete / complete_full / fan_out job for
# that worker; always release in finally.

inflight_waits: int = 0
"""Times a caller blocked waiting for a per-worker in-flight slot."""

# worker_id -> asyncio.Semaphore(n)
_worker_inflight: dict[str, asyncio.Semaphore] = {}
_worker_inflight_mu = threading.Lock()


def _max_inflight() -> int:
    """Read ROUTISM_WORKER_MAX_INFLIGHT (default 2, minimum 1)."""
    raw = os.environ.get("ROUTISM_WORKER_MAX_INFLIGHT", "2").strip() or "2"
    try:
        return max(1, int(raw))
    except ValueError:
        return 2


def _worker_sem(worker_id: str) -> asyncio.Semaphore:
    """Return (creating if needed) the process-wide semaphore for worker_id."""
    with _worker_inflight_mu:
        sem = _worker_inflight.get(worker_id)
        if sem is None:
            sem = asyncio.Semaphore(_max_inflight())
            _worker_inflight[worker_id] = sem
        return sem


@asynccontextmanager
async def _acquire_worker_inflight(worker_id: str):
    """Acquire one in-flight slot for ``worker_id``; release in ``finally``.

    When the semaphore is already fully held, increments ``inflight_waits``
    before awaiting a free slot.
    """
    global inflight_waits
    sem = _worker_sem(worker_id)
    if sem.locked():
        inflight_waits += 1
    await sem.acquire()
    try:
        yield
    finally:
        sem.release()


def reset_worker_inflight_state() -> None:
    """Test helper: clear per-worker semaphores and the wait counter."""
    global inflight_waits
    with _worker_inflight_mu:
        _worker_inflight.clear()
    inflight_waits = 0


def worker_inflight_metrics() -> dict[str, int]:
    """Snapshot of optional in-flight wait counters (process lifetime)."""
    return {"inflight_waits": inflight_waits}


def _auth_headers(worker: Worker) -> dict[str, str]:
    """Build HTTP headers including decrypted BYOK api_key when present."""
    headers = {"content-type": "application/json"}
    key = resolve_api_key(worker.api_key)
    if key:
        headers["authorization"] = f"Bearer {key}"
    return headers


def complete(
    worker: Worker,
    messages: list[dict],
    *,
    timeout: float | None = None,
    max_tokens: int | None = None,
    retries: int = 1,
    backoff: float = 0.5,
) -> str:
    """Call one worker and return the assistant text.

    Guards:
      - timeout: hard per-call deadline (raises WorkerError, no hang).
      - cost cap: max_tokens sent in the request (token ceiling). A $ ceiling
        needs per-model pricing and is deferred to Phase 1.
      - retries: transient failures (WorkerError) are retried with exponential
        backoff (backoff, 2*backoff, 4*backoff, ...). After `retries` attempts
        the last WorkerError is raised. retries=1 means try once (no retry).
      - per-worker in-flight: ROUTISM_WORKER_MAX_INFLIGHT (via complete_full).
    """
    return complete_full(
        worker, messages, timeout=timeout, max_tokens=max_tokens, retries=retries, backoff=backoff
    )[0]


def chat_completions_url(base_url: str) -> str:
    """Build the OpenAI-compatible chat completions URL for a worker base_url.

    Accepts any of:
      - ``https://host/v1``
      - ``https://host/v1/``
      - ``https://host/v1/chat/completions`` (already complete — left alone)
      - bare ``https://host`` (appends ``/v1/chat/completions``)
    so a misconfigured pool entry that already includes the path does not
    become ``.../chat/completions/chat/completions`` (HTTP 404).

    When the API runs in Docker, loopback hosts are rewritten to
    ``host.docker.internal`` so workers on the host machine are reachable.
    """
    url = rewrite_loopback_url_for_container((base_url or "").rstrip("/"))
    if url.endswith("/chat/completions"):
        return url
    if url.endswith("/v1"):
        return url + "/chat/completions"
    # Some gateways use a non-v1 prefix (e.g. /api/gateway); append the path.
    return url + "/chat/completions"


def _complete_full_http(
    worker: Worker,
    messages: list[dict],
    *,
    timeout: float | None,
    max_tokens: int | None,
    retries: int,
    backoff: float,
) -> tuple[str, dict]:
    """Sync HTTP body for complete_full (no in-flight gate — caller holds slot)."""
    timeout = timeout or worker.timeout_s
    max_tokens = max_tokens or worker.max_tokens
    url = chat_completions_url(worker.base_url)
    headers = _auth_headers(worker)
    payload = {
        "model": worker.model,
        "messages": messages,
        "max_tokens": max_tokens,
    }
    last_err: Exception | None = None
    data: dict = {}
    for attempt in range(1, max(retries, 1) + 1):
        try:
            with httpx.Client(timeout=timeout) as client:
                resp = client.post(url, json=payload, headers=headers)
                resp.raise_for_status()
                data = resp.json()
            text = data["choices"][0]["message"]["content"]
            usage = data.get("usage") or {}
            if not usage or "total_tokens" not in usage:
                # Provider omitted usage — fall back to a rough estimate so
                # metrics still move; flag it by using the estimate keys.
                est = _est_usage(text, messages)
                usage = est
            return text, usage
        except httpx.TimeoutException:
            # transient: network/timeout blip -> retry with backoff
            last_err = WorkerError(
                f"timeout after {timeout}s calling worker {worker.id} at {url}"
            )
        except httpx.HTTPStatusError as e:
            status = e.response.status_code
            if 500 <= status < 600:
                # transient server error -> retry with backoff
                last_err = WorkerError(
                    f"HTTP {status} from worker {worker.id}: {e.response.text[:200]}"
                )
            else:
                # 4xx (bad request, auth, not found) is permanent -> fail now,
                # do NOT burn retries on a request that will never succeed.
                raise WorkerError(
                    f"HTTP {status} from worker {worker.id}: {e.response.text[:200]}"
                )
        except httpx.HTTPError as e:
            last_err = WorkerError(f"transport error calling worker {worker.id}: {e}")
        except (KeyError, IndexError, TypeError, ValueError) as e:
            # malformed/empty response body (incl. JSONDecodeError) -> treat as a
            # transient server glitch and retry; after retries, surface it.
            last_err = WorkerError(f"unexpected response from {worker.id}: {e!r}")
        # transient failure -> back off and retry unless this was the last attempt
        if attempt < max(retries, 1):
            time.sleep(backoff * (2 ** (attempt - 1)))
    assert last_err is not None
    raise last_err


def complete_full(
    worker: Worker,
    messages: list[dict],
    *,
    timeout: float | None = None,
    max_tokens: int | None = None,
    retries: int = 1,
    backoff: float = 0.5,
) -> tuple[str, dict]:
    """Like `complete`, but also returns the real token `usage` from the
    provider response (falls back to a char-based estimate if the provider
    omits it). Lets the metrics layer report ACTUAL tokens, not guesses.

    Honors ``ROUTISM_WORKER_MAX_INFLIGHT``: acquires the per-worker asyncio
    semaphore around the HTTP work (via a private event loop when none is
    running so sync callers share the same process-wide budget as fan_out).
    """

    async def _gated() -> tuple[str, dict]:
        async with _acquire_worker_inflight(worker.id):
            return _complete_full_http(
                worker,
                messages,
                timeout=timeout,
                max_tokens=max_tokens,
                retries=retries,
                backoff=backoff,
            )

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        # Normal sync path (executor, gates, /api/plan): own loop for the slot.
        return asyncio.run(_gated())
    # Already inside a running loop (unusual for this sync API). Cannot
    # asyncio.run; fall through ungated rather than deadlock the loop.
    return _complete_full_http(
        worker,
        messages,
        timeout=timeout,
        max_tokens=max_tokens,
        retries=retries,
        backoff=backoff,
    )


def _est_usage(text: str, messages: list[dict]) -> dict:
    """Char-based fallback when a provider omits `usage`."""
    in_chars = sum(len(m.get("content", "")) for m in messages)
    return {
        "prompt_tokens": max(0, in_chars // 4),
        "completion_tokens": max(0, len(text) // 4),
        "total_tokens": max(0, (in_chars + len(text)) // 4),
        "estimated": True,
    }


def timeout_guard_demo(worker: Worker, slow_url: str, slow_seconds: float = 2.0) -> None:
    """Prove the timeout guard fires (raises WorkerError) instead of hanging.

    Used by the P0.B gate: point `slow_url` at an endpoint that sleeps longer
    than `worker.timeout_s`. Expects WorkerError.
    """
    slow = Worker(
        id=worker.id + "_slow",
        provider=worker.provider,
        base_url=slow_url,
        model=worker.model,
        tags=worker.tags,
        api_key_env=worker.api_key_env,
        timeout_s=min(worker.timeout_s, 0.3),
    )
    complete(slow, [{"role": "user", "content": "hi"}])  # must raise WorkerError


def flaky_worker(worker: Worker, failures: int = 2):
    """Test double: an object whose `.complete(...)` fails `failures` times, then
    delegates to the real `worker`. Lets the P1.B gate prove retry-with-backoff
    recovers transient failures WITHOUT a real flaky endpoint.
    """
    real = complete

    class _Flaky:
        n = 0

        def complete(self, messages, *, timeout=None, max_tokens=None, retries=1, backoff=0.5):
            _Flaky.n += 1
            if _Flaky.n <= failures:
                raise WorkerError(f"flaky failure {_Flaky.n}/{failures}")
            return real(worker, messages, timeout=timeout, max_tokens=max_tokens)

    return _Flaky()


# ===========================================================================
# P6.B — ASYNC PARALLEL FAN-OUT
# ---------------------------------------------------------------------------
# Phase 6 builds a REAL multi-LLM parallel orchestration engine: ONE query is
# fanned out to multiple worker models AT ONCE, then the engine judges +
# synthesizes. This module adds the async fan-out layer that calls K workers in
# parallel over a single shared httpx.AsyncClient, guarded by an
# asyncio.Semaphore so we never exceed the pool's concurrency budget.
#
# Guards mirror the synchronous `complete_full` exactly (timeout -> WorkerError,
# 5xx/transport/malformed -> retry w/ backoff, 4xx -> fail now). Per-worker
# failures are ISOLATED: a dead worker returns an error entry in its FanOutResult
# and NEVER raises out of `fan_out` — the rest of the batch still completes.
# ===========================================================================


@dataclass
class FanOutResult:
    """One worker's outcome from a parallel fan-out call.

    `ok` is False exactly when `error` is set (the worker failed or timed out).
    `elapsed_ms` is always populated (even on failure) for trace/latency display.
    `role` is an optional pass-through the engine assigns per worker (P6.E); it
    is NOT decided here.
    """

    worker_id: str
    role: str | None
    answer: str | None
    error: str | None
    elapsed_ms: float
    usage: dict
    ok: bool

    def to_candidate(self, engine_score: float = 0.0, engine_reason: str = "") -> dict:
        """Bridge shape the engine (P6.E) emits on the SSE `candidate` event.

        Field names match ui/lib/api.ts ParallelCandidate EXACTLY so the UI
        lights up with zero extra mapping: {worker_id, role, answer, score,
        score_reason, elapsed_ms, error}. (The UI type uses `score` /
        `score_reason`, NOT `engine_score` / `engine_reason` — those were the
        original author names and did NOT match the consumer, which is why this
        was changed to match the canonical UI contract.)
        """
        return {
            "worker_id": self.worker_id,
            "role": self.role,
            "answer": self.answer,
            "score": engine_score,
            "score_reason": engine_reason,
            "elapsed_ms": self.elapsed_ms,
            "error": self.error,
        }


async def _a_complete_full_http(
    worker: Worker,
    messages: list[dict],
    *,
    client: "httpx.AsyncClient",
    timeout: float | None,
    max_tokens: int | None,
    retries: int,
    backoff: float,
    temperature: float | None = None,
) -> tuple[str, dict]:
    """Async HTTP body (no in-flight gate — caller holds the per-worker slot)."""
    timeout = timeout or worker.timeout_s
    max_tokens = max_tokens or worker.max_tokens
    url = chat_completions_url(worker.base_url)
    headers = _auth_headers(worker)
    payload: dict = {
        "model": worker.model,
        "messages": messages,
        "max_tokens": max_tokens,
    }
    if temperature is not None:
        payload["temperature"] = float(temperature)
    last_err: Exception | None = None
    for attempt in range(1, max(retries, 1) + 1):
        try:
            resp = await client.post(url, json=payload, headers=headers, timeout=timeout)
            resp.raise_for_status()
            data = resp.json()
            text = data["choices"][0]["message"]["content"]
            usage = data.get("usage") or {}
            if not usage or "total_tokens" not in usage:
                usage = _est_usage(text, messages)
            return text, usage
        except httpx.TimeoutException:
            last_err = WorkerError(
                f"timeout after {timeout}s calling worker {worker.id} at {url}"
            )
        except httpx.HTTPStatusError as e:
            status = e.response.status_code
            if 500 <= status < 600:
                last_err = WorkerError(
                    f"HTTP {status} from worker {worker.id}: {e.response.text[:200]}"
                )
            else:
                raise WorkerError(
                    f"HTTP {status} from worker {worker.id}: {e.response.text[:200]}"
                )
        except httpx.HTTPError as e:
            last_err = WorkerError(f"transport error calling worker {worker.id}: {e}")
        except (KeyError, IndexError, TypeError, ValueError) as e:
            last_err = WorkerError(f"unexpected response from {worker.id}: {e!r}")
        # transient failure -> back off and retry unless this was the last attempt
        if attempt < max(retries, 1):
            await asyncio.sleep(backoff * (2 ** (attempt - 1)))
    assert last_err is not None
    raise last_err


async def _a_complete_full(
    worker: Worker,
    messages: list[dict],
    *,
    client: "httpx.AsyncClient",
    timeout: float | None,
    max_tokens: int | None,
    retries: int,
    backoff: float,
    temperature: float | None = None,
) -> tuple[str, dict]:
    """Async twin of `complete_full` — same guards, same return shape.

    Uses the caller-supplied shared `client` and a per-request `timeout` so the
    fan-out can apply a uniform deadline while reusing one connection pool.
    Optional ``temperature`` is forwarded when set (Self-MoA sample diversity).

    Acquires the process-wide per-worker in-flight semaphore
    (``ROUTISM_WORKER_MAX_INFLIGHT``) before HTTP work; released in finally so
    concurrent fan_out / complete_async /v1/run tasks for the same worker_id
    cannot exceed the budget.
    """
    async with _acquire_worker_inflight(worker.id):
        return await _a_complete_full_http(
            worker,
            messages,
            client=client,
            timeout=timeout,
            max_tokens=max_tokens,
            retries=retries,
            backoff=backoff,
            temperature=temperature,
        )


async def complete_async(
    worker: Worker,
    messages: list[dict],
    *,
    timeout: float | None = None,
    max_tokens: int | None = None,
    retries: int = 1,
    backoff: float = 0.5,
) -> str:
    """Async single-worker call. Returns the assistant text (mirrors `complete`)."""
    async with httpx.AsyncClient(timeout=timeout or worker.timeout_s) as client:
        answer, _ = await _a_complete_full(
            worker,
            messages,
            client=client,
            timeout=timeout,
            max_tokens=max_tokens,
            retries=retries,
            backoff=backoff,
        )
    return answer


async def fan_out(
    workers: list[Worker],
    messages: list[dict],
    *,
    concurrency: int | None = None,
    timeout: float | None = None,
    max_tokens: int | None = None,
    retries: int = 1,
    backoff: float = 0.5,
    role_map: dict[str, str] | None = None,
) -> list["FanOutResult"]:
    """Call `workers` in PARALLEL and return one FanOutResult per worker.

    - Concurrency is capped by `asyncio.Semaphore(concurrency or len(workers))`
      so we never exceed the pool's parallelism budget.
    - Per-worker in-flight is also capped by ``ROUTISM_WORKER_MAX_INFLIGHT``
      (default 2) inside `_a_complete_full`, so the same worker_id cannot be
      hammered beyond that limit across concurrent fan_out /v1/run tasks.
    - Per-worker failures are ISOLATED: a dead/slow/erroring worker yields a
      FanOutResult with `ok=False` + `error`, and does NOT abort the others.
    - Order is preserved (results align 1:1 with `workers` by index).
    - One shared `httpx.AsyncClient` is reused across all requests for connection
      efficiency; each request still carries its own `timeout`.

    This is the Phase 6 fan-out primitive the engine calls before judging +
    synthesizing (P6.C / P6.D). The user's worker pool is the black box here —
    engine models are NEVER fanned out through this path (they live in
    `routism_orch`, reserved).
    """
    if not workers:
        return []
    sem = asyncio.Semaphore(concurrency or len(workers))
    role_map = role_map or {}

    async def _one(w: Worker) -> "FanOutResult":
        t0 = time.monotonic()
        async with sem:
            try:
                answer, usage = await _a_complete_full(
                    w,
                    messages,
                    client=client,
                    timeout=timeout,
                    max_tokens=max_tokens,
                    retries=retries,
                    backoff=backoff,
                )
                elapsed = (time.monotonic() - t0) * 1000
                return FanOutResult(w.id, role_map.get(w.id), answer, None, elapsed, usage, True)
            except Exception as e:  # isolation: never let one worker kill the batch
                elapsed = (time.monotonic() - t0) * 1000
                return FanOutResult(w.id, role_map.get(w.id), None, str(e), elapsed, {}, False)

    async with httpx.AsyncClient(timeout=timeout or 30.0) as client:
        results = await asyncio.gather(*[_one(w) for w in workers])
    return list(results)


async def fan_out_stream(
    workers: list[Worker],
    messages: list[dict],
    *,
    concurrency: int | None = None,
    timeout: float | None = None,
    max_tokens: int | None = None,
    retries: int = 1,
    backoff: float = 0.5,
    role_map: dict[str, str] | None = None,
):
    """Like `fan_out`, but yields each FanOutResult AS SOON as that worker finishes.

    Order is completion-order (not pool order). Callers that need a full
    ordered list should buffer. Used by parallel orchestration so the UI
    lights up worker cards immediately instead of waiting for the slowest
    / timed-out worker.
    """
    if not workers:
        return
    sem = asyncio.Semaphore(concurrency or len(workers))
    role_map = role_map or {}

    async def _one(w: Worker) -> "FanOutResult":
        t0 = time.monotonic()
        async with sem:
            try:
                answer, usage = await _a_complete_full(
                    w,
                    messages,
                    client=client,
                    timeout=timeout,
                    max_tokens=max_tokens,
                    retries=retries,
                    backoff=backoff,
                )
                elapsed = (time.monotonic() - t0) * 1000
                return FanOutResult(w.id, role_map.get(w.id), answer, None, elapsed, usage, True)
            except Exception as e:
                elapsed = (time.monotonic() - t0) * 1000
                return FanOutResult(w.id, role_map.get(w.id), None, str(e), elapsed, {}, False)

    async with httpx.AsyncClient(timeout=timeout or 60.0) as client:
        tasks = [asyncio.create_task(_one(w)) for w in workers]
        for fut in asyncio.as_completed(tasks):
            yield await fut


async def fan_out_varied(
    jobs: list[tuple["Worker", list[dict]]],
    *,
    concurrency: int | None = None,
    timeout: float | None = None,
    max_tokens: int | None = None,
    retries: int = 1,
    backoff: float = 0.5,
    role_map: dict[str, str] | None = None,
) -> list["FanOutResult"]:
    """Like `fan_out`, but each worker gets its OWN message list.

    `fan_out` broadcasts a single `messages` payload to every worker — correct
    for parallel mode (same query to all), but WRONG for Conductor mode, where
    each DAG subtask has a distinct prompt (and its own dependency context). This
    primitive takes a list of `(worker, messages)` jobs and runs them in parallel
    with the exact same guards and error isolation as `fan_out`:

    - Concurrency capped by `asyncio.Semaphore(concurrency or len(jobs))`.
    - Per-job failures ISOLATED: a dead/slow worker yields `ok=False` + `error`
      and never aborts the batch.
    - Order preserved (results align 1:1 with `jobs` by index).
    - One shared `httpx.AsyncClient` reused across all requests.

    The same worker may appear in more than one job (e.g. two subtasks routed to
    the same model); results stay index-aligned, so callers must key on position,
    not on `worker_id`.
    """
    if not jobs:
        return []
    sem = asyncio.Semaphore(concurrency or len(jobs))
    role_map = role_map or {}

    async def _one(w: "Worker", messages: list[dict]) -> "FanOutResult":
        t0 = time.monotonic()
        async with sem:
            try:
                answer, usage = await _a_complete_full(
                    w,
                    messages,
                    client=client,
                    timeout=timeout,
                    max_tokens=max_tokens,
                    retries=retries,
                    backoff=backoff,
                )
                elapsed = (time.monotonic() - t0) * 1000
                return FanOutResult(w.id, role_map.get(w.id), answer, None, elapsed, usage, True)
            except Exception as e:  # isolation: never let one job kill the batch
                elapsed = (time.monotonic() - t0) * 1000
                return FanOutResult(w.id, role_map.get(w.id), None, str(e), elapsed, {}, False)

    async with httpx.AsyncClient(timeout=timeout or 30.0) as client:
        results = await asyncio.gather(*[_one(w, msgs) for (w, msgs) in jobs])
    return list(results)


# Handoff-named alias for the parallel fan-out primitive (Master Plan §3.3 calls
# it `complete_many_async`; canonical name is `fan_out`). Same behaviour.
complete_many_async = fan_out
