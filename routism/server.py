"""P0.A -> P0.E — OpenAI-compatible API + chat UI.

Endpoints:
  GET  /                         -> simple chat UI (test Phase 0 as a whole)
  GET  /v1/models                -> lists the single model "routism-ultra"
  POST /v1/chat/completions       -> orchestrate -> execute -> synthesize (real flow)
  POST /api/plan                  -> returns the full trace (classify + plan + steps + answer)

Run:  python3 -m routism.run
"""
from __future__ import annotations

import os
import json
import asyncio
import time
import threading
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from typing import Any

from . import config as cfg, orchestrator as orch, executor as ex, classifier as clf
from .schema import Workflow, Step
from .worker import WorkerError
from .config import OrchestratorNotConfigured
from .config import OrchestratorNotConfigured
from .management import router as management_router
from . import openai_compat as oai

# P5.A — Phase 5 learned orchestration engine (separate package, own registry).
# The engine owns the coordinator SLM + dedicted verifier in `orch.yaml` with a
# `reserved` flag; those models are NEVER user-selectable app workers. Until the
# head is trained (P5.C) the engine degrades to the app's safe_plan fallback, so
# a weak engine can't 500 a request.
from routism_orch import orchestrate as orch_orchestrate, get_registry as orch_registry
from routism_orch import orchestrate_parallel
from routism_orch.orchestrate_parallel import parallel_orchestrate_stream  # degraded internal only
from routism_orch.orchestrate_fast import (
    fast_path_enabled as orch_fast_path_enabled,
    self_moa_fast_stream,
)
from routism_orch.conductor import (
    plan_dag,
    planner_backend,
    heuristic_plan,
    single_task_plan,
)
from routism_orch.orchestrate_conductor import execute_conductor_dag, execute_conductor_stream
from routism_orch import engine_client as orch_engine_client
from routism_orch.assign import (
    assign_v2_enabled as orch_assign_v2_enabled,
    snapshot_worker_health as orch_snapshot_worker_health,
)
from routism_orch.controller import resolve_path as orch_resolve_path
from routism.api_keys import router as keys_router, ensure_bootstrap_key, require_auth, extract_bearer, authorize_request
from routism.benchmarks import router as benchmarks_router
from routism.rate_limit import RateLimitMiddleware
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

_log = logging.getLogger(__name__)

# Load .env / .env.local early so worker api_key_env resolves on import paths
try:
    from routism.run import _load_dotenv_files

    _load_dotenv_files()
except Exception:  # noqa: BLE001
    pass


async def _asgi_iter(async_gen):
    """Bridge an async generator to one compatible with StreamingResponse.

    Starlette/FastAPI's StreamingResponse accepts sync iterators, sync
    generators, or async iterators — but NOT async generators directly. We
    convert by polling `__anext__` and yielding strings.
    """
    it = async_gen()
    while True:
        try:
            chunk = await it.__anext__()
        except StopAsyncIteration:
            return
        if chunk:
            yield chunk


# ---------------------------------------------------------------------------
# B8 ROBUSTNESS: register exception handlers so the dashboard (U4) always gets
# JSON, never an HTML 500 trace. HTTPException (400/401/404/...) keeps FastAPI's
# native JSON; only genuinely unhandled errors become a JSON 500. Validation
# errors become a JSON 422. Registered via the constructor dict (bulletproof).
# ---------------------------------------------------------------------------
def _unhandled_handler(request, exc: Exception):
    if isinstance(exc, StarletteHTTPException):
        raise exc  # native JSON 400/401/404/...
    return JSONResponse(
        {"error": "internal server error", "detail": str(exc)}, status_code=500
    )


def _validation_handler(request, err: RequestValidationError):
    return JSONResponse(
        {"error": "invalid request", "detail": err.errors()}, status_code=422
    )


MODEL_ID = "routism-ultra"
CONFIG_PATH = "routism.yaml"

# Process-wide lock for any read-modify-write of routism.yaml from server.py
# (settings PUT). management.py has its own for pool writes; the two never run
# concurrently on the same file path in practice, but we still avoid half-writes.
_lock = threading.Lock()


@asynccontextmanager
async def _lifespan(app: FastAPI):
    """PR-2: best-effort pin eng-thinker + eng-verifier at startup; unpin on exit.

    Pin runs in a daemon thread so a cold Ollama load cannot block server boot.
    Fail-open: if Ollama is down or models are missing, the request path still
    degrades via engine_models_ready (PR-1). Lazy pin inside call_engine_model
    covers the race if a request arrives before the background pin finishes.
    """
    def _bg_pin() -> None:
        try:
            orch_engine_client.ensure_engine_pinned(orch_registry())
        except Exception as e:
            _log.warning("engine pin at startup skipped: %s: %s", type(e).__name__, e)

    threading.Thread(target=_bg_pin, name="engine-pin", daemon=True).start()
    try:
        ensure_bootstrap_key()
    except Exception as e:
        _log.warning("api key bootstrap skipped: %s: %s", type(e).__name__, e)
    yield
    try:
        await asyncio.to_thread(orch_engine_client.unpin_engine_models, orch_registry())
    except Exception as e:
        _log.warning("engine unpin at shutdown skipped: %s: %s", type(e).__name__, e)


app = FastAPI(
    title="Routism",
    version="0.0.1",
    lifespan=_lifespan,
    exception_handlers={
        Exception: _unhandled_handler,
        RequestValidationError: _validation_handler,
    },
)

# P4.A/C: allow the Next.js dashboard (default :3000) to call this API from the
# browser. The dashboard is a thin client over this backend; CORS is required
# for fetch() calls to succeed under the browser same-origin policy.
# B3 SECURITY: lock CORS to the exact methods/headers the dashboard actually
# uses (was allow_methods=["*"] + allow_headers=["*"] + credentials — too wide).
ALLOWED_ORIGINS = ["http://localhost:3000", "http://127.0.0.1:3000"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["content-type", "authorization", "x-routism-user-id"],
)
# Public API abuse control (sliding window per client IP)
app.add_middleware(RateLimitMiddleware)

app.include_router(management_router)
app.include_router(keys_router)
app.include_router(benchmarks_router)



# ---------------------------------------------------------------------------
# B2 SECURITY: protect the management API (pool add/remove, settings, health).
# The dashboard mutates the live provider pool, so unauthenticated access on a
# non-loopback host would let anyone reconfigure the orchestrator. Gate rule:
#   - If MANAGEMENT_API_KEY is set: require `Authorization: Bearer <key>`.
#   - If unset: allow ONLY loopback (127.0.0.1 / ::1) and log a warning. This
#     keeps the local dev/dashboard flow working without secrets, while refusing
#     any off-box request until a key is configured.
# ---------------------------------------------------------------------------
def _client_is_loopback(request: Request) -> bool:
    """True if the HTTP client is loopback (delegates to host_reach helper)."""
    from routism.host_reach import client_is_loopback_host

    host = (request.client.host if request.client else "") or ""
    return client_is_loopback_host(host)


def require_management_auth(request: Request) -> None:
    """Gate management POST/DELETE/PUT.

    - MANAGEMENT_API_KEY set → require Bearer.
    - Unset + loopback client → allow (native API on laptop).
    - Unset + private client (Docker bridge) + ROUTISM_OPEN_LOCAL=1 → allow
      so stock ``docker compose`` + browser on published :8000 works without a
      manual management key.
    - Unset + public client → 401 (set MANAGEMENT_API_KEY for remote dashboard).
    """
    from routism.host_reach import management_client_allowed

    key = (os.environ.get("MANAGEMENT_API_KEY") or "").strip()
    auth = request.headers.get("authorization", "")
    bearer_ok = bool(key) and auth == f"Bearer {key}"
    client_host = (request.client.host if request.client else "") or ""
    host_header = request.headers.get("host") or ""

    if key and not bearer_ok:
        raise HTTPException(
            status_code=401,
            detail="invalid or missing management API key",
        )

    if management_client_allowed(
        client_host,
        management_key=key or None,
        bearer_ok=bearer_ok if key else False,
        host_header=host_header,
    ):
        return

    import logging

    logging.warning(
        "Management request refused from %s Host=%r (no MANAGEMENT_API_KEY / not local). "
        "Open http://localhost:8000 from this machine, or set MANAGEMENT_API_KEY.",
        client_host or "unknown",
        host_header,
    )
    raise HTTPException(
        status_code=401,
        detail=(
            "management API is locked: open the dashboard via http://localhost:3000 "
            "(API on localhost:8000), or set MANAGEMENT_API_KEY for remote access"
        ),
    )


# Apply the auth dependency to management MUTATION routes only (POST/DELETE +
# ollama start/stop). Read-only status (GET /pool, GET /health) stays open so the
# local dashboard can render provider status without a key; the dangerous
# reconfigure actions always require MANAGEMENT_API_KEY (or loopback when unset).
for _route in management_router.routes:
    if _route.methods and not _route.methods.isdisjoint({"POST", "DELETE", "PUT"}):
        _existing = list(getattr(_route, "dependencies", []))
        _existing.append(Depends(require_management_auth))
        _route.dependencies = _existing


# ---------------------------------------------------------------------------
# B4 NEW: GET /v1/metrics — observability for the dashboard (U3).
# Returns pool size/capacity, orchestrator/verifier ids, live worker health
# summary, and the last Phase-2 eval (accuracy / token overhead / win-loss) from
# Routism/phase2_results.json when present.
# ---------------------------------------------------------------------------
import pathlib
import httpx

_METRICS_PATH = pathlib.Path(__file__).resolve().parent.parent / "phase2_results.json"


@app.get("/v1/metrics")
def metrics() -> dict:
    try:
        settings = cfg.load(CONFIG_PATH)
    except FileNotFoundError:
        settings = None
    eval_data = None
    if _METRICS_PATH.exists():
        try:
            eval_data = json.loads(_METRICS_PATH.read_text())
        except Exception:
            eval_data = None
    pool = None
    if settings is not None:
        # light health summary without making live calls
        pool = {
            "size": len(settings.workers),
            "capacity": 5,
            "orchestrator_worker_id": settings.orchestrator_worker_id,
            "verifier_worker_id": settings.verifier_worker_id,
            "workers": [w.id for w in settings.workers],
        }
    # Last Conductor run models_used (trajectory log); best-effort.
    models_used: list[str] = []
    trajectory_meta: dict = {}
    try:
        from routism_orch.trajectory import last_models_used, last_trajectory_meta

        models_used = last_models_used()
        trajectory_meta = last_trajectory_meta()
    except Exception:
        models_used = []
        trajectory_meta = {}
    return {
        "pool": pool,
        "eval": eval_data,
        "engine": orch_engine_client.engine_metrics(),
        "models_used": models_used,
        "trajectory": trajectory_meta,
        "generated_at": int(time.time()),
    }


# ---------------------------------------------------------------------------
# B7 NEW: GET /v1/health — aggregate reachability probe for ALL workers in one
# call (so the dashboard U3 can render a health overview without N fetches, and
# without needing the management auth key). Read-only + open. Each entry mirrors
# the management /health/{id} probe (HEAD-style /v1/models reachability).
# ---------------------------------------------------------------------------
@app.get("/v1/health")
def health_all() -> dict:
    """Aggregate reachability for the whole pool.

    Same rule as ``GET /v1/management/health/{id}``: only HTTP 2xx is
    ``reachable: true``. 401/403/404 are unhealthy with a clear error.
    """
    try:
        settings = cfg.load(CONFIG_PATH)
    except FileNotFoundError:
        return {"workers": [], "generated_at": int(time.time())}
    from .crypto_keys import resolve_api_key
    from .health_probe import classify_models_probe, models_probe_url
    from .host_reach import connection_refused_hint, rewrite_loopback_url_for_container

    out = []
    for w in settings.workers:
        probe_base = rewrite_loopback_url_for_container(w.base_url)
        url = models_probe_url(probe_base)
        headers = {}
        key = resolve_api_key(w.api_key)
        if key:
            headers["Authorization"] = f"Bearer {key}"
        try:
            with httpx.Client(timeout=min(5.0, getattr(w, "timeout_s", 5.0))) as client:
                r = client.get(url, headers=headers)
            out.append(
                classify_models_probe(
                    worker_id=w.id,
                    status_code=r.status_code,
                    api_key_configured=bool(key),
                    url=url,
                )
            )
        except Exception as e:
            hint = connection_refused_hint(probe_base)
            out.append(
                classify_models_probe(
                    worker_id=w.id,
                    status_code=None,
                    api_key_configured=bool(key),
                    url=url,
                    transport_error=f"{type(e).__name__}: {e}. {hint}",
                )
            )
    return {"workers": out, "generated_at": int(time.time())}


class ChatMessage(BaseModel):
    """OpenAI-style message; content may be a string or multimodal parts list."""

    model_config = ConfigDict(extra="ignore")

    role: str
    content: Any = ""


class ChatCompletionRequest(BaseModel):
    """OpenAI Chat Completions request (extra fields ignored for agent clients)."""

    model_config = ConfigDict(extra="ignore")

    model: str = MODEL_ID
    messages: list[ChatMessage] = Field(default_factory=list)
    temperature: float | None = 0.7
    max_tokens: int | None = None
    stream: bool = False
    stream_options: dict[str, Any] | None = None
    n: int | None = 1
    # Conductor-only product. Legacy "parallel"/"auto" accepted, coerced to conductor.
    mode: str | None = None  # "conductor" (preferred); "parallel"|"auto" → conductor

    @field_validator("n", mode="before")
    @classmethod
    def _n_default(cls, v: Any) -> Any:
        return 1 if v is None else v


# B5 SECURITY/ROBUSTNESS: bound chat input so a malformed/abusive client can't
# push an unbounded prompt through the orchestrator. Empty queries are rejected
# with 400; oversized ones are truncated (see openai_compat caps).
_MAX_PROMPT_CHARS = 8_000


def _extract_query(req: ChatCompletionRequest) -> str:
    """Fold full messages[] into a Conductor query (OpenAI agent multi-turn)."""
    try:
        return oai.build_agent_prompt(list(req.messages))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


def _build_workflow(query: str, settings):
    """Classify + build the workflow.

    Returns (mode, workflow, used_fallback). `used_fallback` is True when a
    complex query could NOT be planned by the (possibly weak) Conductor and was
    degraded to a single direct step — so the API/UI can flag degraded routing.

    P5.A: complex queries route through the Phase-5 learned engine
    (`routism_orch.orchestrate`). The engine is told to use the app's
    `orch.safe_plan` as its fallback while its head is untrained, so a weak
    engine can never fail an entire request. Trivial queries keep the existing
    direct path (no engine overhead on cheap calls).
    """
    if not settings.workers:
        raise WorkerError("no model is currently selected")
    mode = clf.classify(query)
    used_fallback = False
    if mode == "trivial":
        try:
            best = settings.orchestrator
        except OrchestratorNotConfigured as e:
            raise WorkerError(str(e))
        workflow = Workflow(steps=[Step(subtask=query, worker_id=best.id, access_list=[])])
    else:
        # Route complex queries through the learned engine. It returns a
        # Workflow (via P5.C loop, or via safe_plan fallback until then).
        result = orch_orchestrate(
            query,
            [w.id for w in settings.workers],
            settings,
            fallback=orch.safe_plan,
        )
        workflow = result.workflow
        used_fallback = result.used_fallback
    return mode, workflow, used_fallback


# ---------------------------------------------------------------------------
# 7E: Auto-detection with Capability Registry
# ---------------------------------------------------------------------------

def _is_complex_query(query: str) -> bool:
    """
    Determine if a query should use Conductor mode (multi-step DAG)
    vs Parallel mode (single fan-out).
    
    Uses heuristic keyword indicators.
    """
    complex_indicators = [
        " then ", " then write ", " then explain ", " and then ",
        " also ", " step by step ", " break down ", " first ",
        " second ", " third ", " next ", " after ", " followed by ",
        " then create ", " then implement ", " then test ",
        " then debug ", " then optimize ", " then refactor ",
    ]
    return (
        any(indicator in query.lower() for indicator in complex_indicators)
        or len(query.split()) > 50
    )


async def _plan_conductor_dag(query: str, settings, *, registry):
    """Conductor DAG planning via reserved engine only (eng-thinker).

    IRON RULE: user workers never plan. ENGINE ≠ WORKERS.
    PLANNER_BACKEND=pool is ignored; always plan_dag → engine_client.
    """
    worker_tags = {w.id: list(w.tags) for w in settings.workers}
    health = None
    if orch_assign_v2_enabled() and settings.workers:
        health = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: orch_snapshot_worker_health(list(settings.workers)),
        )

    # planner_backend() is always "engine"; kept so env experiments stay no-ops.
    _ = planner_backend()
    return await plan_dag(
        query,
        registry=registry,
        worker_tags=worker_tags,
        health=health,
    )


@app.get("/v1/orch/registry")
def orch_registry_endpoint() -> dict:
    """P5.A — expose the Phase-5 engine's OWN model registry.

    Returns every engine-internal model (coordinator SLM + dedicated verifier)
    plus the `reserved_ids` set. The UI uses `reserved_ids` to filter engine
    models out of the Add-Worker dropdown + Providers list, fixing the leak
    where gemma/qwen appeared as selectable workers.
    """
    try:
        reg = orch_registry()
    except FileNotFoundError:
        return {"models": [], "reserved_ids": []}
    return reg.as_dict()


@app.get("/v1/orch/capability-registry")
def capability_registry_endpoint() -> dict:
    """7E — expose the capability registry for UI/auto-detection.

    Returns the capability_registry section from orch.yaml with descriptions
    and example subtasks for each capability tag. Used by UI for worker
    tagging and by auto-detection logic for multi-capability queries.
    """
    try:
        reg = orch_registry()
    except FileNotFoundError:
        return {"capabilities": {}}
    return {"capabilities": reg.capability_registry()}


@app.get("/v1/models")
def list_models() -> dict:
    return {
        "object": "list",
        "data": [
            {
                "id": MODEL_ID,
                "object": "model",
                "created": 0,
                "owned_by": "routism",
                "routism": {"kind": "orchestrator", "note": "routes to a 1-5 worker pool"},
            }
        ],
    }


def _ensure_conductor_plan(query: str, settings, registry, *, mode: str = "conductor"):
    """Build a Conductor plan: LLM → heuristic multi-step → single-node.

    Never returns an empty plan when workers exist — product is Conductor-only.
    """
    plan = None
    try:
        plan = asyncio.run(_plan_conductor_dag(query, settings, registry=registry))
    except Exception as e:
        print(f"Conductor planning failed: {e}")
        plan = None
    worker_tags = {w.id: list(w.tags) for w in settings.workers}
    health = None
    if orch_assign_v2_enabled() and settings.workers:
        try:
            health = orch_snapshot_worker_health(list(settings.workers))
        except Exception:
            health = None
    if plan is None or not plan.subtasks:
        try:
            plan = heuristic_plan(query, worker_tags, health=health)
            if plan.subtasks:
                print(f"Conductor: heuristic plan ({len(plan.subtasks)} subtasks)")
        except Exception as e:
            print(f"Conductor heuristic plan failed: {e}")
            plan = None
    if plan is None or not plan.subtasks:
        try:
            plan = single_task_plan(query, worker_tags, health=health)
            print("Conductor: single-task plan (whole query)")
        except Exception as e:
            print(f"Conductor single-task plan failed: {e}")
            plan = None
    _ = mode
    return plan


def _openai_error_response(
    message: str,
    *,
    status_code: int,
    type_: str = "invalid_request_error",
    code: str | None = None,
) -> JSONResponse:
    return JSONResponse(
        oai.format_error(message, type_=type_, code=code),
        status_code=status_code,
    )


def _http_exc_to_openai(e: HTTPException) -> JSONResponse:
    """Map FastAPI HTTPException (auth/billing) to OpenAI error envelope."""
    if isinstance(e.detail, dict):
        msg = (
            e.detail.get("error")
            or e.detail.get("message")
            or e.detail.get("detail")
            or json.dumps(e.detail)
        )
        if isinstance(msg, dict):
            msg = msg.get("message") or json.dumps(msg)
    else:
        msg = str(e.detail)
    if e.status_code == 402:
        type_, code = "insufficient_quota", "insufficient_quota"
    elif e.status_code == 401:
        type_, code = "invalid_request_error", "invalid_api_key"
    else:
        type_, code = "invalid_request_error", None
    return _openai_error_response(str(msg), status_code=e.status_code, type_=type_, code=code)


def _load_settings():
    """Single-tenant: always host routism.yaml pool."""
    return cfg.load(CONFIG_PATH)


def _run_conductor_for_chat(query: str, user_id: str | None = None) -> dict:
    """Execute Conductor (or parallel fallback). Returns final dict with answer/usage.

    Overridable in tests via ``routism.server._run_conductor_for_chat``.
    ``user_id`` is ignored (single-tenant install); kept for call-site compat.
    """
    _ = user_id
    settings = _load_settings()
    registry = orch_registry()
    plan = _ensure_conductor_plan(query, settings, registry, mode="conductor")
    final = None
    if plan is not None and plan.subtasks and registry is not None:
        final, _events = asyncio.run(
            execute_conductor_dag(query, settings, plan, registry=registry)
        )
    if final is None:
        final, _events = asyncio.run(
            orchestrate_parallel.parallel_orchestrate_events(query, settings),
        )
    if isinstance(final, dict):
        final.setdefault(
            "routism_pool",
            {
                "worker_ids": [w.id for w in settings.workers],
                "source": "yaml",
            },
        )
    return final


@app.post("/v1/chat/completions")
async def chat_completions(req: ChatCompletionRequest, request: Request):
    """OpenAI-compatible chat completions (Conductor orchestration).

    Supports ``stream: false`` (JSON) and ``stream: true`` (SSE chat.completion.chunk).
    Extra body fields (e.g. ``tools``) are ignored — tools stay in the agent.
    """
    # n > 1 not supported
    if req.n is not None and int(req.n) != 1:
        return _openai_error_response(
            "Only n=1 is supported",
            status_code=400,
            code="invalid_n",
        )

    try:
        query = _extract_query(req)
    except HTTPException as e:
        msg = e.detail if isinstance(e.detail, str) else str(e.detail)
        return _openai_error_response(msg, status_code=e.status_code)

    mode = (req.mode or "conductor").strip().lower()
    if mode not in ("parallel", "conductor", "auto", ""):
        return _openai_error_response(
            f"invalid mode: {req.mode}, must be 'conductor' (legacy: parallel|auto)",
            status_code=400,
        )
    mode = "conductor"

    try:
        require_auth(request.headers.get("authorization"), request, for_mutation=False)
    except HTTPException as e:
        return _http_exc_to_openai(e)

    model_id = req.model or MODEL_ID
    include_usage = bool(
        isinstance(req.stream_options, dict) and req.stream_options.get("include_usage")
    )

    if not req.stream:
        try:
            final = await asyncio.to_thread(_run_conductor_for_chat, query)
            answer = oai.apply_max_tokens(final.get("answer") or "", req.max_tokens)
            usage = final.get("usage") or {}
            body = oai.format_completion(
                answer,
                model=model_id,
                usage=usage,
                extra={
                    "parallel": final.get("parallel", {}),
                    "routism": {
                        "orchestration_input_tokens": 0,
                        "orchestration_output_tokens": 0,
                        "worker_prompt_tokens": usage.get("prompt_tokens", 0),
                        "worker_completion_tokens": usage.get("completion_tokens", 0),
                        "budget_hit": final.get("budget_hit", False),
                        "parallel_engine": "routism-ultra",
                        "pool": final.get("routism_pool"),
                    },
                },
            )
            return JSONResponse(body)
        except WorkerError as e:
            # Prefer 200 with assistant error content for legacy; agents prefer OpenAI error.
            # Use OpenAI error at 502 for failed workers.
            return _openai_error_response(
                str(e),
                status_code=502,
                type_="server_error",
                code="worker_error",
            )
        except FileNotFoundError as e:
            return _openai_error_response(str(e), status_code=500, type_="server_error")
        except Exception as e:  # noqa: BLE001
            _log.exception("chat.completions failed")
            return _openai_error_response(
                f"{type(e).__name__}: {e}",
                status_code=500,
                type_="server_error",
            )

    # ---- stream: true — role + keepalive during Conductor, then chunk answer ----
    async def event_stream():
        frame, cid, created = oai.sse_role_chunk(model_id)
        yield frame
        result_box: dict[str, Any] = {}
        err_box: dict[str, str] = {}

        def _work() -> None:
            try:
                result_box["final"] = _run_conductor_for_chat(query)
            except Exception as e:  # noqa: BLE001
                err_box["err"] = f"{type(e).__name__}: {e}"

        task = asyncio.create_task(asyncio.to_thread(_work))
        try:
            while not task.done():
                try:
                    await asyncio.wait_for(asyncio.shield(task), timeout=15.0)
                except asyncio.TimeoutError:
                    yield oai.sse_keepalive_chunk(model_id, cid, created)
            await task
        except Exception as e:  # noqa: BLE001
            err_box["err"] = f"{type(e).__name__}: {e}"

        if err_box.get("err"):
            # Emit error as content then stop (some clients ignore mid-stream HTTP)
            err_text = f"[routism error] {err_box['err']}"
            for piece in oai.iter_sse_after_answer(
                err_text,
                model=model_id,
                usage={},
                include_usage=False,
                completion_id_str=cid,
            ):
                # skip duplicate role from helper — we already sent role
                if '"role"' in piece and '"assistant"' in piece and '"content"' not in piece:
                    continue
                yield piece
            return

        final = result_box.get("final") or {}
        answer = oai.apply_max_tokens(final.get("answer") or "", req.max_tokens)
        usage = final.get("usage") or {}
        # Content chunks only (role already sent)
        for piece in oai.chunk_text(answer, size=48):
            if piece:
                yield oai.sse_data(
                    oai._chunk_dict(
                        cid=cid,
                        model=model_id,
                        created=created,
                        delta={"content": piece},
                    )
                )
        yield oai.sse_data(
            oai._chunk_dict(
                cid=cid,
                model=model_id,
                created=created,
                delta={},
                finish_reason="stop",
            )
        )
        if include_usage:
            usage_chunk = oai._chunk_dict(cid=cid, model=model_id, created=created, delta={})
            usage_chunk["usage"] = {
                "prompt_tokens": int(usage.get("prompt_tokens") or 0),
                "completion_tokens": int(usage.get("completion_tokens") or 0),
                "total_tokens": int(
                    usage.get("total_tokens")
                    or (
                        int(usage.get("prompt_tokens") or 0)
                        + int(usage.get("completion_tokens") or 0)
                    )
                ),
            }
            yield oai.sse_data(usage_chunk)
        yield oai.sse_data("[DONE]")

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/plan")
def api_plan(req: ChatCompletionRequest) -> JSONResponse:
    """Full trace: classifier mode, orchestrator plan, per-step outputs, answer."""
    try:
        query = _extract_query(req)
    except HTTPException as e:
        return JSONResponse({"error": e.detail}, status_code=e.status_code)
    try:
        settings = cfg.load(CONFIG_PATH)
        mode, workflow, used_fallback = _build_workflow(query, settings)
        trace = ex.run_detailed(workflow, settings)
        return JSONResponse(
            {
                "mode": mode,
                "degraded": used_fallback,
                "pool": [w.id for w in settings.workers],
                "plan": [
                    {"worker_id": s.worker_id, "subtask": s.subtask, "access_list": s.access_list}
                    for s in workflow.steps
                ],
                "steps": trace["steps"],
                "answer": trace["answer"],
                "orchestration_input_tokens": trace["orchestration_input_tokens"],
                "orchestration_output_tokens": trace["orchestration_output_tokens"],
                "worker_prompt_tokens": trace.get("worker_prompt_tokens", 0),
                "worker_completion_tokens": trace.get("worker_completion_tokens", 0),
                "total_tokens": trace.get("total_tokens", 0),
                "budget_hit": trace["budget_hit"],
            },
        )
    except WorkerError as e:
        return JSONResponse({"error": f"[routism error] {e}"}, status_code=200)


@app.post("/v1/run")
def api_run(req: ChatCompletionRequest, request: Request):
    """Conductor-only orchestration run (SSE).

    Emits the event SHAPES ui/lib/api.ts dispatches:
      event: meta       -> {mode, degraded, pool, orchestration}
      event: conductor_plan, dag_layer_*, fan_out, step, scores, synthesis
      event: done       -> {answer, parallel: {conductor, ...}, usage, ...}
      event: error      -> {message}

    Always Conductor. Legacy mode=parallel|auto coerced to conductor.
    Model B: debits run price from credit balance (card/UPI top-ups).
    """
    try:
        query = _extract_query(req)
    except HTTPException as e:
        def _err():
            yield 'event: error\ndata: ' + json.dumps({"message": e.detail}) + "\n\n"
        return StreamingResponse(_err(), media_type="text/event-stream")

    mode = (req.mode or "conductor").strip().lower()
    if mode not in ("parallel", "conductor", "auto"):
        def _err():
            yield 'event: error\ndata: ' + json.dumps({
                "message": f"invalid mode: {req.mode}, must be 'conductor' (legacy: parallel|auto)"
            }) + "\n\n"
        return StreamingResponse(_err(), media_type="text/event-stream")
    mode = "conductor"

    try:
        require_auth(request.headers.get("authorization"), request, for_mutation=False)
    except HTTPException as e:
        def _err():
            yield 'event: error\ndata: ' + json.dumps({"message": str(e.detail)}) + "\n\n"
        return StreamingResponse(_err(), media_type="text/event-stream", status_code=401)

    try:
        settings = _load_settings()
    except FileNotFoundError:
        def _err():
            yield 'event: error\ndata: ' + json.dumps({"message": "routism.yaml not found"}) + "\n\n"
        return StreamingResponse(_err(), media_type="text/event-stream")

    async def _events():
        """Always Conductor: LLM plan → heuristic multi-step → single-node.

        Parallel stream is only a last-resort emergency if plan construction fails.
        """
        _ = orch_resolve_path(query, mode)  # always "team"; kept for telemetry hooks
        registry = orch_registry()
        plan = None
        try:
            plan = await _plan_conductor_dag(query, settings, registry=registry)
        except Exception as e:
            print(f"Conductor planning failed: {e}")
            plan = None
        worker_tags = {w.id: list(w.tags) for w in settings.workers}
        health = None
        if orch_assign_v2_enabled() and settings.workers:
            try:
                health = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: orch_snapshot_worker_health(list(settings.workers)),
                )
            except Exception:
                health = None
        if plan is None or not plan.subtasks:
            try:
                plan = heuristic_plan(query, worker_tags, health=health)
                if plan.subtasks:
                    print(f"Conductor SSE: heuristic plan ({len(plan.subtasks)} subtasks)")
            except Exception as e:
                print(f"Conductor heuristic plan failed: {e}")
                plan = None
        if plan is None or not plan.subtasks:
            try:
                plan = single_task_plan(query, worker_tags, health=health)
                print("Conductor SSE: single-task plan (whole query)")
            except Exception as e:
                print(f"Conductor single-task plan failed: {e}")
                plan = None
        if plan is not None and plan.subtasks and registry is not None:
            async for ev in execute_conductor_stream(query, settings, plan, registry=registry):
                yield ev
            return

        # Emergency only (no workers / plan construction hard-failed)
        async for ev in parallel_orchestrate_stream(query, settings):
            yield ev

    async def event_stream():
        try:
            async for ev in _events():
                ev = dict(ev)  # don't mutate the source dict
                kind = ev.pop("_event")
                ev.pop("_internal", None)
                # SSE frame; trailing blank line flushes the event to the client
                yield f"event: {kind}\ndata: {json.dumps(ev)}\n\n"
        except Exception as e:
            yield 'event: error\ndata: ' + json.dumps({"message": f"{type(e).__name__}: {e}"}) + "\n\n"
            return

    return StreamingResponse(
        _asgi_iter(event_stream),
        media_type="text/event-stream",
        headers={
            # Prevent proxies / browsers from buffering the live event stream.
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


class SettingsIn(BaseModel):
    max_repairs: int | None = None
    max_total_tokens: int | None = None
    memory_backend: str | None = None
    memory_scope: str | None = None
    # U5: let the dashboard pin the conductor / verifier to a pool worker id.
    orchestrator_worker_id: str | None = None
    verifier_worker_id: str | None = None


@app.get("/v1/settings", dependencies=[Depends(require_management_auth)])
def get_settings() -> dict:
    """U5 — current global settings (NOT worker pool)."""
    try:
        s = cfg.load(CONFIG_PATH)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="routism.yaml not found on server")
    return {
        "max_repairs": s.max_repairs,
        "max_total_tokens": s.max_total_tokens,
        "memory_backend": s.memory_backend,
        "memory_scope": s.memory_scope,
        "orchestrator_worker_id": s.orchestrator_worker_id,
        "verifier_worker_id": s.verifier_worker_id,
    }


@app.put("/v1/settings", dependencies=[Depends(require_management_auth)])
def put_settings(body: SettingsIn) -> dict:
    """U5 — update global settings (round-trips through Settings() validators)."""
    with _lock:
        try:
            s = cfg.load(CONFIG_PATH)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="routism.yaml not found on server")
        if body.max_repairs is not None:
            s.max_repairs = max(0, int(body.max_repairs))
        if body.max_total_tokens is not None:
            s.max_total_tokens = max(0, int(body.max_total_tokens))
        if body.memory_backend is not None:
            if body.memory_backend not in ("inprocess", "file", "sqlite"):
                raise HTTPException(status_code=400, detail="memory_backend must be inprocess|file|sqlite")
            s.memory_backend = body.memory_backend
            if body.memory_backend != "inprocess" and not s.memory_path:
                s.memory_path = "routism_memory.jsonl" if body.memory_backend == "file" else "routism_memory.db"
        if body.memory_scope is not None:
            s.memory_scope = body.memory_scope
        if body.orchestrator_worker_id is not None:
            if body.orchestrator_worker_id and body.orchestrator_worker_id not in {w.id for w in s.workers}:
                raise HTTPException(
                    status_code=400,
                    detail=f"orchestrator_worker_id {body.orchestrator_worker_id!r} not in pool",
                )
            s.orchestrator_worker_id = body.orchestrator_worker_id or None
        if body.verifier_worker_id is not None:
            if body.verifier_worker_id and body.verifier_worker_id not in {w.id for w in s.workers}:
                raise HTTPException(
                    status_code=400,
                    detail=f"verifier_worker_id {body.verifier_worker_id!r} not in pool",
                )
            s.verifier_worker_id = body.verifier_worker_id or None
        cfg.save(s, CONFIG_PATH)
    return {"ok": True}


UI_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Routism — Chat</title>
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  body { margin: 0; font: 15px/1.5 ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, sans-serif;
         background: #0d1117; color: #e6edf3; }
  .wrap { max-width: 860px; margin: 0 auto; padding: 24px; }
  h1 { font-size: 20px; margin: 0 0 4px; }
  .sub { color: #8b949e; font-size: 13px; margin-bottom: 16px; }
  #log { background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 12px;
         height: 56vh; overflow-y: auto; }
  .msg { margin: 8px 0; }
  .msg .who { font-weight: 600; font-size: 12px; color: #58a6ff; }
  .msg.assistant .who { color: #3fb950; }
  .bubble { background: #0d1117; border: 1px solid #30363d; border-radius: 8px; padding: 10px; margin-top: 4px; white-space: pre-wrap; }
  .plan { margin-top: 10px; border-top: 1px dashed #30363d; padding-top: 8px; font-size: 13px; }
  .plan summary { cursor: pointer; color: #d29922; font-weight: 600; }
  .step { border: 1px solid #30363d; border-radius: 6px; padding: 8px; margin: 6px 0; }
  .step .meta { color: #8b949e; font-size: 12px; }
  .step .out { white-space: pre-wrap; margin-top: 4px; }
  form { display: flex; gap: 8px; margin-top: 12px; }
  input[type=text] { flex: 1; background: #161b22; border: 1px solid #30363d; color: #e6edf3;
                     border-radius: 8px; padding: 10px 12px; font-size: 15px; }
  button { background: #238636; color: #fff; border: 0; border-radius: 8px; padding: 10px 16px;
           font-size: 15px; cursor: pointer; }
  button:disabled { opacity: .5; cursor: default; }
  .err { color: #f85149; }
</style>
</head>
<body>
<div class="wrap">
  <h1>Routism</h1>
  <div class="sub">OpenAI-compatible orchestrator. Type a question — trivial queries short-circuit to 1 step, complex ones get a multi-step plan across your worker pool.</div>
  <div id="log"></div>
  <form id="f">
    <input id="q" type="text" placeholder="Ask anything… (e.g. 'What is 2+2?' or 'Design a REST API, then write tests')" autocomplete="off" />
    <button id="send" type="submit">Send</button>
  </form>
</div>
<script>
const log = document.getElementById('log');
const form = document.getElementById('f');
const q = document.getElementById('q');
const send = document.getElementById('send');

function addMsg(who, text, cls) {
  const d = document.createElement('div');
  d.className = 'msg ' + (cls || who.toLowerCase());
  d.innerHTML = '<div class="who">' + who + '</div><div class="bubble"></div>';
  d.querySelector('.bubble').textContent = text;
  log.appendChild(d); log.scrollTop = log.scrollHeight;
  return d;
}
function addPlan(data) {
  const det = document.createElement('details');
  det.className = 'plan'; det.open = false;
  const summ = document.createElement('summary');
  summ.textContent = 'Pipeline: mode=' + data.mode + ' · steps=' + data.plan.length + ' · pool=[' + data.pool.join(', ') + ']';
  det.appendChild(summ);
  data.steps.forEach((s, i) => {
    const sd = document.createElement('div'); sd.className = 'step';
    const ctx = s.saw_prior_context ? 'uses prior context (access_list=' + JSON.stringify(s.access_list) + ')' : 'no prior context';
    sd.innerHTML = '<div class="meta">step ' + i + ' → worker <b>' + s.worker_id + '</b> · ' + ctx + '</div>'
                 + '<div class="out"></div>';
    sd.querySelector('.out').textContent = s.output;
    det.appendChild(sd);
  });
  log.appendChild(det); log.scrollTop = log.scrollHeight;
}

form.addEventListener('submit', async (e) => {
  e.preventDefault();
  const text = q.value.trim(); if (!text) return;
  q.value = ''; send.disabled = true;
  addMsg('You', text, 'user');
  const wait = addMsg('Routism', 'thinking…', 'assistant');
  try {
    const r = await fetch('/api/plan', {
      method: 'POST', headers: {'content-type': 'application/json'},
      body: JSON.stringify({ model: 'routism-ultra', messages: [{ role: 'user', content: text }] })
    });
    const data = await r.json();
    if (data.error) { wait.querySelector('.bubble').textContent = data.error; wait.querySelector('.bubble').className = 'bubble err'; }
    else {
      wait.querySelector('.bubble').textContent = data.answer;
      addPlan(data);
    }
  } catch (err) {
    wait.querySelector('.bubble').textContent = 'request failed: ' + err;
    wait.querySelector('.bubble').className = 'bubble err';
  } finally { send.disabled = false; q.focus(); }
});
q.focus();
</script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
def ui() -> str:
    return UI_HTML


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
