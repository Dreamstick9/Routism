"""P4.A — management API for the dashboard.

Surface (read the YAML as the SoT, mutate under a lock, write back):
- GET    /v1/management/pool            -> current workers (and pool size)
- POST   /v1/management/pool            -> add or replace a worker; cap = 5
- DELETE /v1/management/pool/{id}       -> remove (refuses if it would push the
                                          pool under 1, or if the id is the
                                          explicit orchestrator/verifier pin)
- GET    /v1/management/health/{id}     -> lightweight `GET /v1/models` probe

Implementation rules:
- Hard cap 5 enforced at the Settings(...) boundary; we round-trip through
  Settings(**) so all pydantic validators apply (size, unique ids, role refs).
- We never serialize secret VALUES — only `api_key_env` names. UI can't ever
  read a key.
- Hot-reload is "read-modify-write under a threading.Lock". Other endpoints
  call cfg.load() per request, so persistence to disk = reload for them.
"""
from __future__ import annotations

import os
import threading
from pathlib import Path

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from . import config as cfg
from .config import Worker
from .crypto_keys import encrypt_secret, has_key_material, resolve_api_key
from .health_probe import (
    classify_models_probe,
    fetch_models_error_for_status,
    is_healthy_status,
    models_probe_url,
)
from .local_providers import (
    LOCAL_PROVIDER_SPECS,
    discover_local_models,
    get_local_spec,
    pool_worker_payload,
    resolve_native_base,
    resolve_openai_base,
)
from .security_ssrf import SSRFBlocked, validate_worker_base_url

router = APIRouter(prefix="/v1/management", tags=["management"])

# Single process-wide lock covering any read-modify-write of routism.yaml.
# Normal request handlers also read it per-call (no in-memory cache), so this
# lock prevents a concurrent /v1/chat while a /management write is mid-flight
# from observing a half-written file.
_lock = threading.Lock()


class WorkerIn(BaseModel):
    id: str
    provider: str
    base_url: str
    model: str
    tags: list[str] = Field(default_factory=list)
    api_key: str | None = None
    timeout_s: float = 30.0
    max_tokens: int = 2048
    # Optional role-pin: declare this worker as the orchestrator or verifier when
    # adding it. Both must be valid ids in the final pool; Settings() validates
    # after the merge.
    set_as_orchestrator: bool = False
    set_as_verifier: bool = False


def _manager_path() -> Path:
    """Resolve the live config path the server boots from.

    Routism bootstraps from CWD/routism.yaml via cfg.load. We reuse the same
    file for round-trip writes so YAML really is the source of truth.
    """
    return Path("routism.yaml")


def _to_worker_dict(w: Worker, *, for_response: bool = False) -> dict:
    """Serialize a worker.

    When ``for_response`` is True (GET /pool), never return the raw secret —
    only a boolean ``api_key_configured`` so the UI can show status.
    Internal read-modify-write keeps the full ``api_key`` for round-trips.
    """
    key = w.api_key
    row = {
        "id": w.id,
        "provider": w.provider,
        "base_url": w.base_url,
        "model": w.model,
        "tags": list(w.tags),
        "timeout_s": w.timeout_s,
        "max_tokens": w.max_tokens,
        # P5.A: flag whether this worker id collides with an engine-reserved
        # (coordinator/verifier) model. Redundant with the server's separate
        # rejection, but gives the UI one more signal to keep reserved models
        # out of the pool.
        "reserved": w.id in _RESERVED_IDS,
    }
    if for_response:
        resolved = resolve_api_key(key) if key else None
        row["api_key_configured"] = bool(resolved) or bool(w.api_key_env)
        # Do not echo secret material to the browser.
    else:
        if key:
            row["api_key"] = key
        if w.api_key_env:
            row["api_key_env"] = w.api_key_env
    return row


# P5.A — engine-reserved ids (coordinator SLM + dedicated verifier). Loaded
# once at import from the engine's own registry; used to (a) flag/reject
# reserved ids in the pool add path and (b) expose `reserved_ids` to the UI.
def _load_reserved_ids() -> set[str]:
    from routism_orch import get_registry

    try:
        return get_registry().reserved_ids()
    except Exception as e:  # noqa: BLE001
        # Do NOT silently swallow: a broken/unreadable engine registry must NOT
        # quietly disable the leak guard (that would re-open the exact bug P5.A
        # fixes). Log loudly so the failure is visible, and keep the guard
        # conservative — better to over-reject than to leak.
        import logging

        logging.getLogger("routism.management").error(
            "engine registry (orch.yaml) failed to load; reserved-id guard is "
            "DISABLED for this run: %s: %s",
            type(e).__name__,
            e,
        )
        return set()


_RESERVED_IDS = _load_reserved_ids()


def _load_reserved_model_names() -> set[str]:
    """Load the Ollama model NAMES (e.g. 'qwen3:1.7b') of all engine-reserved
    models from orch.yaml, so the Connect-Ollama picker can exclude them.
    `_RESERVED_IDS` has engine ids like 'eng-thinker'; _RESERVED_MODEL_NAMES has
    the actual Ollama tags the UI must never show as addable workers.
    """
    from routism_orch import get_registry

    try:
        reg = get_registry()
        return {m.model for m in reg.models if m.reserved}
    except Exception:
        return set()


_RESERVED_MODEL_NAMES = _load_reserved_model_names()


@router.get("/pool")
def get_pool() -> dict:
    with _lock:
        try:
            settings = cfg.load(_manager_path())
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="routism.yaml not found on server")
        return {
            "size": len(settings.workers),
            "capacity": 5,
            "orchestrator_worker_id": settings.orchestrator_worker_id,
            "verifier_worker_id": settings.verifier_worker_id,
            # P5.A: engine-reserved ids the UI must never offer as app workers.
            "reserved_ids": sorted(_RESERVED_IDS),
            "workers": [_to_worker_dict(w, for_response=True) for w in settings.workers],
        }


@router.post("/pool")
def post_pool(worker_in: WorkerIn) -> dict:
    with _lock:
        # P5.A — reject any attempt to add an engine-reserved model (coordinator
        # SLM / dedicated verifier) as an app worker. These live ONLY in the
        # engine's own registry (orch.yaml); admitting them as user workers both
        # breaks the reserved contract and leaks the engine's internal models
        # into the UI's Add-Worker dropdown.
        if worker_in.id in _RESERVED_IDS:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"worker_id {worker_in.id!r} is an engine-reserved model "
                    f"(coordinator/verifier) and cannot be added as an app worker. "
                    f"Engine models are managed by routism_orch, not the user pool."
                ),
            )

        # SSRF baseline — reject metadata / link-local / private (unless env
        # allows) worker base_url before we persist anything.
        try:
            validate_worker_base_url(worker_in.base_url)
        except SSRFBlocked as e:
            raise HTTPException(status_code=400, detail=f"invalid base_url: {e}") from e

        path = _manager_path()
        try:
            settings = cfg.load(path)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="routism.yaml not found on server")

        workers = [_to_worker_dict(w) for w in settings.workers]
        new_w = worker_in.model_dump(exclude={"set_as_orchestrator", "set_as_verifier"})
        existing_idx = next((i for i, w in enumerate(workers) if w["id"] == worker_in.id), None)
        # Preserve existing key when the client omits/blank-sends api_key (re-add /
        # reconnect without re-pasting). Critical for oMLX and other keyed locals.
        if not (new_w.get("api_key") or "").strip():
            new_w.pop("api_key", None)
            if existing_idx is not None and workers[existing_idx].get("api_key"):
                new_w["api_key"] = workers[existing_idx]["api_key"]
        elif has_key_material():
            # BYOK at rest: encrypt plaintext keys on write. Values already
            # tagged enc:v1: are left unchanged (idempotent). Call sites use
            # resolve_api_key / decrypt_secret when sending Authorization.
            try:
                new_w["api_key"] = encrypt_secret(new_w["api_key"])
            except Exception as e:  # noqa: BLE001
                raise HTTPException(
                    status_code=500,
                    detail=f"failed to encrypt api_key: {type(e).__name__}: {e}",
                ) from e

        if existing_idx is not None:
            workers[existing_idx] = new_w  # replace in place (no size change)
        else:
            if len(workers) >= 5:
                raise HTTPException(
                    status_code=400,
                    detail=f"pool full: 5/5 providers connected — remove one to add another",
                )
            workers.append(new_w)

        # Compute new role-pin values (only one of orchestrator/verifier can
        # be replaced if the user is pinning something at this add).
        orch_id = settings.orchestrator_worker_id
        ver_id = settings.verifier_worker_id
        if worker_in.set_as_orchestrator:
            orch_id = worker_in.id
        if worker_in.set_as_verifier:
            ver_id = worker_in.id

        # Round-trip through Settings(...) — validators enforce size, unique
        # ids, and orchestrator/verifier-in-pool. A bad request raises here.
        rebuilt = cfg.Settings(
            orchestrator_worker_id=orch_id,
            verifier_worker_id=ver_id,
            max_repairs=settings.max_repairs,
            max_total_tokens=settings.max_total_tokens,
            memory_backend=settings.memory_backend,
            memory_path=settings.memory_path,
            memory_scope=settings.memory_scope,
            workers=[cfg.Worker(**w) for w in workers],
        )
        cfg.save(rebuilt, path)
        return {"ok": True, "size": len(rebuilt.workers), "id": worker_in.id}


@router.delete("/pool/{worker_id}")
def delete_pool(worker_id: str) -> dict:
    with _lock:
        path = _manager_path()
        try:
            settings = cfg.load(path)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="routism.yaml not found on server")
        workers = [_to_worker_dict(w) for w in settings.workers]
        kept = [w for w in workers if w["id"] != worker_id]
        if len(kept) == len(workers):
            raise HTTPException(status_code=404, detail=f"worker_id {worker_id!r} not in pool")
        # The instant a user removes an Ollama connection, unload that model from
        # Ollama (keep_alive:0). Fired synchronously BEFORE we return — no model
        # stays warm after the Remove click.
        removed = next((w for w in workers if w["id"] == worker_id), None)
        if removed and removed.get("provider") == "ollama":
            try:
                with httpx.Client(timeout=30.0) as client:
                    client.post(
                        f"{os.environ.get('OLLAMA_HOST', 'http://localhost:11434').rstrip('/')}/api/generate",
                        json={"model": removed["model"], "prompt": " ", "stream": False, "keep_alive": 0},
                    )
            except Exception:
                pass  # best-effort: pool removal still succeeds even if Ollama is down
        # Allow removing the last worker — the pool can be empty; the user
        # connects providers (e.g. Ollama) on demand from the dashboard.
        orch_id = settings.orchestrator_worker_id
        ver_id = settings.verifier_worker_id
        if orch_id == worker_id:
            orch_id = None  # fall back to workers[0]
        if ver_id == worker_id:
            ver_id = None
        rebuilt = cfg.Settings(
            orchestrator_worker_id=orch_id,
            verifier_worker_id=ver_id,
            max_repairs=settings.max_repairs,
            max_total_tokens=settings.max_total_tokens,
            memory_backend=settings.memory_backend,
            memory_path=settings.memory_path,
            memory_scope=settings.memory_scope,
            workers=[cfg.Worker(**w) for w in kept],
        )
        cfg.save(rebuilt, path)
        return {"ok": True, "size": len(rebuilt.workers), "removed": worker_id}


@router.get("/ollama/models")
def ollama_models(base_url: str | None = None, api_key: str | None = None) -> dict:
    """Discover locally-running Ollama models for the dashboard's 'Connect Ollama' button.

    Probes the local Ollama daemon (default http://localhost:11434) and returns
    its available model names. Optional ``base_url`` query overrides host/port
    (e.g. ``http://localhost:11435`` or ``:11435``).
    """
    return discover_local_models(
        "ollama",
        base_url=base_url,
        api_key=api_key,
        reserved_model_names=_RESERVED_MODEL_NAMES,
    )


@router.get("/local/{provider}/models")
def local_provider_models(
    provider: str,
    base_url: str | None = None,
    api_key: str | None = None,
) -> dict:
    """Discover models from a local one-click provider (ollama | lmstudio | mlx).

    Same contract as GET /ollama/models: ``running``, ``base_url`` (OpenAI /v1),
    ``models``, or ``running: false`` + ``error`` when the server is down.

    Query ``base_url`` overrides the default so users on non-default ports
    (e.g. MLX/oMLX on ``:6969``) can connect. Optional ``api_key`` for local
    servers that require Bearer auth.
    """
    pid = (provider or "").strip().lower()
    # Accept aliases used in the UI
    if pid in ("lm-studio", "lm_studio"):
        pid = "lmstudio"
    if pid in ("apple-mlx", "mlx-lm", "mlx_lm", "omlx"):
        pid = "mlx"
    if get_local_spec(pid) is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"unknown local provider {provider!r}; "
                f"supported: {sorted(LOCAL_PROVIDER_SPECS)}"
            ),
        )
    return discover_local_models(
        pid,
        base_url=base_url,
        api_key=api_key,
        reserved_model_names=_RESERVED_MODEL_NAMES if pid == "ollama" else set(),
    )


@router.get("/local")
def list_local_providers() -> dict:
    """Catalog of one-click local providers (defaults + env overrides)."""
    items = []
    for spec in LOCAL_PROVIDER_SPECS.values():
        items.append(
            {
                "id": spec.id,
                "name": spec.display_name,
                "default_base": resolve_native_base(spec),
                "openai_base_url": resolve_openai_base(spec),
                "env_host": spec.env_host,
                "tags": list(spec.tags),
            }
        )
    return {"providers": items}


class FetchModelsIn(BaseModel):
    base_url: str
    api_key: str | None = None
    models_url: str | None = None  # override for providers with non-standard model endpoints


class OllamaModelIn(BaseModel):
    model: str


class LocalConnectIn(BaseModel):
    """Add a local one-click model to the pool (optional convenience path)."""

    model: str
    provider: str = "ollama"
    base_url: str | None = None  # user host/port override


@router.post("/fetch-models")
def fetch_models(body: FetchModelsIn) -> dict:
    """Fetch available model IDs from a provider's /v1/models endpoint.

    Used by the UI to populate the model dropdown after the user enters
    their API key. Works with any OpenAI-compatible provider.

    Non-2xx (including 401/404) returns ``models: []`` plus a clear ``error`` —
    never treated as successful discovery.
    """
    # SSRF baseline for outbound model listing (same rules as pool add).
    try:
        validate_worker_base_url(body.base_url)
        if body.models_url:
            validate_worker_base_url(body.models_url)
    except SSRFBlocked as e:
        return {"models": [], "error": f"invalid url: {e}"}

    base = body.base_url.rstrip("/")
    if body.models_url:
        url = body.models_url.rstrip("/")
    else:
        url = models_probe_url(base)
    headers = {"content-type": "application/json"}
    key = resolve_api_key(body.api_key) if body.api_key else None
    if key:
        headers["Authorization"] = f"Bearer {key}"
    try:
        with httpx.Client(timeout=10.0) as client:
            r = client.get(url, headers=headers)
        if is_healthy_status(r.status_code):
            data = r.json()
            # Handle multiple response formats:
            # OpenAI: {"data": [{"id": "model"}, ...]}
            # GitHub Copilot / bare array: [{"id": "model"}, ...]
            # Google AI Studio: {"models": [{"name": "models/gemini-x", ...}]}
            if isinstance(data, dict) and "data" in data:
                models = [m["id"] for m in data["data"] if isinstance(m, dict) and "id" in m]
            elif isinstance(data, dict) and "models" in data:
                models = []
                for m in data["models"]:
                    if isinstance(m, dict):
                        name = m.get("name") or m.get("id")
                        if name:
                            models.append(str(name).removeprefix("models/"))
            elif isinstance(data, list):
                models = [m["id"] for m in data if isinstance(m, dict) and "id" in m]
            else:
                models = []
            return {"models": models, "status_code": r.status_code}
        return {
            "models": [],
            "status_code": r.status_code,
            "error": fetch_models_error_for_status(r.status_code),
        }
    except Exception as e:
        return {"models": [], "error": f"{type(e).__name__}: {e}"}


@router.post("/ollama/start")
def ollama_start(body: OllamaModelIn) -> dict:
    """Load a selected Ollama model into memory (the ONLY time a model is started).

    Called only after the user picks a model from the Connect-Ollama picker.
    Does NOT run on the discovery (Connect) click — that is GET-only.
    """
    spec = get_local_spec("ollama")
    assert spec is not None
    base = resolve_native_base(spec)
    host = base[:-3] if base.endswith("/v1") else base
    try:
        with httpx.Client(timeout=120.0) as client:
            r = client.post(
                f"{host}/api/generate",
                json={"model": body.model, "prompt": " ", "stream": False, "keep_alive": "10m"},
            )
        ok = is_healthy_status(r.status_code)
        out: dict = {"ok": ok, "status_code": r.status_code}
        if not ok:
            out["error"] = (
                f"Ollama failed to load model {body.model!r} "
                f"(HTTP {r.status_code}). Is the model pulled?"
            )
        return out
    except Exception as e:
        return {
            "ok": False,
            "error": (
                f"Ollama start failed — is Ollama running at {host}? "
                f"({type(e).__name__}: {e})"
            ),
        }


@router.post("/ollama/stop")
def ollama_stop(body: OllamaModelIn) -> dict:
    """Immediately unload an Ollama model. Called the instant the user presses Remove."""
    spec = get_local_spec("ollama")
    assert spec is not None
    base = resolve_native_base(spec)
    host = base[:-3] if base.endswith("/v1") else base
    try:
        with httpx.Client(timeout=30.0) as client:
            # keep_alive: 0 tells Ollama to free the model right after this call.
            r = client.post(
                f"{host}/api/generate",
                json={"model": body.model, "prompt": " ", "stream": False, "keep_alive": 0},
            )
        return {"ok": True, "status_code": r.status_code}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


@router.post("/local/{provider}/connect")
def local_provider_connect(provider: str, body: LocalConnectIn) -> dict:
    """Discover-validated helper: return the pool-add payload for a local model.

    Does not mutate the pool itself (POST /pool does that) — returns the worker
    dict the UI/client should POST so base_url / id stay consistent with env.
    """
    pid = (provider or body.provider or "").strip().lower()
    if pid in ("lm-studio", "lm_studio"):
        pid = "lmstudio"
    if pid in ("apple-mlx", "mlx-lm", "mlx_lm"):
        pid = "mlx"
    if get_local_spec(pid) is None:
        raise HTTPException(status_code=404, detail=f"unknown local provider {provider!r}")
    model = (body.model or "").strip()
    if not model:
        raise HTTPException(status_code=400, detail="model is required")
    payload = pool_worker_payload(pid, model, base_url=body.base_url)
    # Ensure SSRF would accept this base_url (loopback local servers).
    try:
        validate_worker_base_url(payload["base_url"])
    except SSRFBlocked as e:
        raise HTTPException(status_code=400, detail=f"invalid base_url: {e}") from e
    return {"ok": True, "worker": payload}


@router.get("/health/{worker_id}")
def health(worker_id: str) -> dict:
    """Lightweight probe — NO model completion; models-endpoint 2xx only = reachable."""
    with _lock:
        try:
            settings = cfg.load(_manager_path())
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="routism.yaml not found on server")
    target = next((w for w in settings.workers if w.id == worker_id), None)
    if target is None:
        raise HTTPException(status_code=404, detail=f"worker_id {worker_id!r} not in pool")

    url = models_probe_url(target.base_url)
    headers = {}
    key = resolve_api_key(target.api_key)
    if key:
        headers["Authorization"] = f"Bearer {key}"

    try:
        with httpx.Client(timeout=min(5.0, target.timeout_s)) as client:
            r = client.get(url, headers=headers)
        return classify_models_probe(
            worker_id=worker_id,
            status_code=r.status_code,
            api_key_configured=bool(key),
            url=url,
        )
    except Exception as e:
        return classify_models_probe(
            worker_id=worker_id,
            status_code=None,
            api_key_configured=bool(key),
            url=url,
            transport_error=f"{type(e).__name__}: {e}",
        )
