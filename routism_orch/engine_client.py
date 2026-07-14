"""Phase 6 — engine-side model client.

Drives the ENGINE-INTERNAL models (eng-thinker / eng-verifier / eng-judge2, all
reserved in `orch.yaml`) through the local Ollama OpenAI-compatible endpoint
(http://localhost:11434/v1/chat/completions). This is the engine TALKING TO ITS
OWN BRAINS — it is NOT the user's worker pool.

Why a separate client from `routism.worker`:
  * engine models are discovered from `orch.yaml` (reserved), never from the app
    pool, so the ENGINE ≠ WORKERS boundary is enforced in code.
  * eng-thinker needs Qwen3 thinking mode ON (arXiv:2509.13332: +~10pt judge
    accuracy). Ollama returns the reasoning in a `reasoning` field (NOT a
    <think> block); we capture it in `.thinking`. Some engines also leak a bare
    control token (e.g. a trailing "/think") into `content` — we strip those.
  * timeout/retry guards mirror `routism.worker.complete_full`.

PR-2 (Conductor architecture):
  * Process-wide `threading.Lock` around every Ollama engine HTTP call so
    concurrent `/v1/chat/completions` (each `asyncio.run` → new loop) and
    `/v1/run` SSE cannot thrash Ollama. `asyncio.Lock` is loop-bound and wrong.
  * `/api/generate` keep_alive pin (same pattern as `management.ollama_start`)
    so thinker/verifier stay resident; judge2 pins lazily on first use.

Imports are kept light (only httpx + the local registry) so this module is safe
to import from server.py / gate scripts.
"""
from __future__ import annotations

import logging
import os
import re
import threading
import time
from dataclasses import dataclass
from typing import Any

import httpx

from .registry import OrchModel, OrchRegistry

_log = logging.getLogger(__name__)

_DEFAULT_OLLAMA_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
_THINK_RE = re.compile(r"<think>.*?</think>", flags=re.DOTALL)
# Bare control tokens some engines (Ollama Qwen3 thinking mode) leak into the
# deliverable `content` after stripping the full block — e.g. a trailing "/think"
# or stray "<think>"/"</think:6124c78e>". These are protocol artifacts, not answer text.
_THINK_ARTIFACT_RE = re.compile(r"</?think>|/think", flags=re.IGNORECASE)

# ---------------------------------------------------------------------------
# PR-2 — process-wide engine serialization + residency
# ---------------------------------------------------------------------------
# Why threading.Lock (not asyncio.Lock): chat completions use asyncio.run per
# request (new event loop each time); SSE uses the app loop; call_engine_model
# is sync httpx often run via run_in_executor. Only a process-wide thread lock
# serializes across all of those.
_ENGINE_LOCK = threading.Lock()
_engine_wait_ms_total = 0.0
_engine_hold_ms_total = 0.0
_metrics_lock = threading.Lock()  # protect float counters under concurrent readers

# Pin state: tags already warmed via /api/generate keep_alive.
_pinned_tags: set[str] = set()
_startup_pin_done = False


def _engine_serialize_enabled() -> bool:
    """ENGINE_SERIALIZE default ON (correctness). Set 0/false/off to debug only."""
    v = os.environ.get("ENGINE_SERIALIZE", "1").strip().lower()
    return v not in ("0", "false", "no", "off")


def engine_metrics() -> dict[str, float]:
    """Snapshot of lock wait/hold totals (milliseconds, process lifetime)."""
    with _metrics_lock:
        return {
            "engine_wait_ms_total": _engine_wait_ms_total,
            "engine_hold_ms_total": _engine_hold_ms_total,
        }


def _record_wait_hold(wait_ms: float, hold_ms: float) -> None:
    global _engine_wait_ms_total, _engine_hold_ms_total
    with _metrics_lock:
        _engine_wait_ms_total += wait_ms
        _engine_hold_ms_total += hold_ms


def _ollama_root(base_url: str) -> str:
    root = base_url.rstrip("/")
    if root.endswith("/v1"):
        root = root[: -len("/v1")]
    return root


def _default_verifier_keep_alive() -> str:
    """10m on ≤16GB machines (verifier dominates RAM); 30m otherwise."""
    try:
        # Linux
        pages = os.sysconf("SC_PHYS_PAGES")
        page_size = os.sysconf("SC_PAGE_SIZE")
        gb = (pages * page_size) / (1024**3)
        return "10m" if gb <= 16.0 else "30m"
    except (AttributeError, OSError, ValueError):
        pass
    try:
        # macOS
        import subprocess

        out = subprocess.check_output(
            ["sysctl", "-n", "hw.memsize"], text=True, timeout=2.0
        ).strip()
        gb = int(out) / (1024**3)
        return "10m" if gb <= 16.0 else "30m"
    except Exception:
        return "10m"


def _pin_tag(
    tag: str,
    *,
    base_url: str = _DEFAULT_OLLAMA_URL,
    keep_alive: str | int = "30m",
    timeout: float = 120.0,
) -> bool:
    """POST /api/generate with keep_alive — same pattern as management.ollama_start.

    Returns True on HTTP 200. Fail-open: logs and returns False on error so a
    cold/missing model never hard-fails the product path.
    """
    if not tag:
        return False
    if tag in _pinned_tags and keep_alive != 0:
        return True
    url = _ollama_root(base_url) + "/api/generate"
    payload = {
        "model": tag,
        "prompt": " ",
        "stream": False,
        "keep_alive": keep_alive,
    }
    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(url, json=payload)
            ok = resp.status_code == 200
            if ok:
                if keep_alive == 0:
                    _pinned_tags.discard(tag)
                else:
                    _pinned_tags.add(tag)
                _log.info("engine pin ok model=%s keep_alive=%s", tag, keep_alive)
            else:
                _log.warning(
                    "engine pin HTTP %s model=%s body=%s",
                    resp.status_code,
                    tag,
                    (resp.text or "")[:200],
                )
            return ok
    except Exception as e:
        _log.warning("engine pin failed model=%s: %s: %s", tag, type(e).__name__, e)
        return False


def pin_engine_models(
    registry: OrchRegistry | None = None,
    *,
    base_url: str = _DEFAULT_OLLAMA_URL,
    keep_alive_thinker: str = "30m",
    keep_alive_verifier: str | None = None,
    include_judge2: bool = False,
    keep_alive_judge2: str = "10m",
    timeout: float = 120.0,
) -> dict[str, bool]:
    """Warm engine brains via `/api/generate` keep_alive under the engine lock.

    Order: thinker, then verifier (RAM-dominant last among the min set).
    judge2 is optional — default lazy on first pairwise use.

    Holds `_ENGINE_LOCK` for the whole pin so concurrent chat/SSE cannot race
    Ollama during load. Fail-open per model.
    """
    reg = registry or OrchRegistry.load(
        os.path.join(os.path.dirname(__file__), "orch.yaml")
    )
    if keep_alive_verifier is None:
        keep_alive_verifier = _default_verifier_keep_alive()

    plan: list[tuple[str, str]] = []  # (tag, keep_alive)
    thinker = reg.coordinator()
    verifier = reg.verifier()
    if thinker:
        plan.append((thinker.model, keep_alive_thinker))
    if verifier:
        plan.append((verifier.model, keep_alive_verifier))
    if include_judge2:
        j2 = reg.judge2()
        if j2:
            plan.append((j2.model, keep_alive_judge2))

    results: dict[str, bool] = {}
    t0 = time.perf_counter()
    acquired = _ENGINE_LOCK.acquire(blocking=True)
    wait_ms = (time.perf_counter() - t0) * 1000.0
    hold_start = time.perf_counter()
    try:
        for tag, ka in plan:
            results[tag] = _pin_tag(
                tag, base_url=base_url, keep_alive=ka, timeout=timeout
            )
    finally:
        hold_ms = (time.perf_counter() - hold_start) * 1000.0
        if acquired:
            _ENGINE_LOCK.release()
        _record_wait_hold(wait_ms, hold_ms)
    return results


def ensure_engine_pinned(
    registry: OrchRegistry | None = None,
    *,
    base_url: str = _DEFAULT_OLLAMA_URL,
    force: bool = False,
) -> dict[str, bool] | None:
    """Idempotent startup/first-use pin of thinker + verifier.

    Returns pin results dict, or None if already done and not forced.
    """
    global _startup_pin_done
    if _startup_pin_done and not force:
        return None
    # Serialize the "once" decision with the engine lock via pin_engine_models.
    results = pin_engine_models(registry, base_url=base_url, include_judge2=False)
    _startup_pin_done = True
    return results


def unpin_engine_models(
    registry: OrchRegistry | None = None,
    *,
    base_url: str = _DEFAULT_OLLAMA_URL,
) -> dict[str, bool]:
    """Best-effort keep_alive:0 for all reserved engine tags (process shutdown)."""
    reg = registry or OrchRegistry.load(
        os.path.join(os.path.dirname(__file__), "orch.yaml")
    )
    results: dict[str, bool] = {}
    t0 = time.perf_counter()
    acquired = _ENGINE_LOCK.acquire(blocking=True)
    wait_ms = (time.perf_counter() - t0) * 1000.0
    hold_start = time.perf_counter()
    try:
        for m in reg.engine_models():
            results[m.model] = _pin_tag(
                m.model, base_url=base_url, keep_alive=0, timeout=30.0
            )
    finally:
        hold_ms = (time.perf_counter() - hold_start) * 1000.0
        if acquired:
            _ENGINE_LOCK.release()
        _record_wait_hold(wait_ms, hold_ms)
    return results


def _keep_alive_for_role(role: str) -> str:
    if role == "coordinator":
        return "30m"
    if role == "verifier":
        return _default_verifier_keep_alive()
    if role == "judge2":
        return "10m"
    return "10m"


def _ensure_model_pinned_unlocked(
    model: OrchModel,
    *,
    base_url: str,
) -> None:
    """Lazy pin the specific model tag (caller must hold _ENGINE_LOCK or accept race)."""
    if model.model in _pinned_tags:
        return
    _pin_tag(
        model.model,
        base_url=base_url,
        keep_alive=_keep_alive_for_role(model.role),
        timeout=120.0,
    )


class EngineModelError(Exception):
    """Raised when an engine-internal model call fails (timeout / HTTP / shape)."""


@dataclass
class EngineResponse:
    content: str            # deliverable text (think artifacts stripped for thinkers)
    thinking: str | None    # raw reasoning block, if the model emitted one
    usage: dict
    model_id: str


def _strip_think(text: str) -> tuple[str, str | None]:
    """Return (content_without_think_artifacts, think_block_or_None).

    Strips full <think>...</think> blocks AND bare control tokens (/think,
    <think>, </think>) so protocol leftovers never reach the deliverable.
    """
    m = _THINK_RE.search(text)
    if not m:
        return _THINK_ARTIFACT_RE.sub("", text).strip(), None
    think = m.group(0)
    content = _THINK_ARTIFACT_RE.sub("", _THINK_RE.sub("", text)).strip()
    return content, think


def _call_engine_model_http(
    model: OrchModel,
    messages: list[dict],
    *,
    base_url: str,
    timeout: float,
    max_tokens: int,
    temperature: float,
    retries: int,
    backoff: float,
    think_override: bool | None,
) -> EngineResponse:
    """Actual Ollama chat HTTP (must run under _ENGINE_LOCK when serialize is on)."""
    url = _ollama_root(base_url) + "/v1/chat/completions"
    headers = {"content-type": "application/json"}
    payload: dict[str, Any] = {
        "model": model.model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    # Qwen3 thinking mode. Use think_override if a caller forced it, else the
    # model's registry flag (eng-thinker keeps thinking; the judge overrides off).
    use_think = model.thinking if think_override is None else think_override
    if use_think:
        payload["think"] = True

    last_err: Exception | None = None
    data: dict = {}
    for attempt in range(1, max(retries, 1) + 1):
        try:
            with httpx.Client(timeout=timeout) as client:
                resp = client.post(url, json=payload, headers=headers)
                resp.raise_for_status()
                data = resp.json()
            msg = data["choices"][0]["message"]
            text = msg.get("content") or ""
            # Ollama returns thinking-mode reasoning in a `reasoning` field (NOT a
            # <think> block). Capture it for the trace; content is already clean
            # of the full block, but bare control tokens may remain.
            thinking = msg.get("reasoning") or None
            usage = data.get("usage") or {}
            if not usage or "total_tokens" not in usage:
                usage = {
                    "prompt_tokens": max(0, sum(len(m.get("content", "")) for m in messages) // 4),
                    "completion_tokens": max(0, len(text) // 4),
                    "total_tokens": max(0, (sum(len(m.get("content", "")) for m in messages) + len(text)) // 4),
                    "estimated": True,
                }
            content, _ = _strip_think(text)
            return EngineResponse(
                content=content,
                thinking=thinking,
                usage=usage,
                model_id=model.id,
            )
        except httpx.TimeoutException:
            last_err = EngineModelError(f"timeout after {timeout}s calling engine model {model.id}")
        except httpx.HTTPStatusError as e:
            status = e.response.status_code
            if 500 <= status < 600:
                last_err = EngineModelError(f"HTTP {status} from engine model {model.id}: {e.response.text[:200]}")
            else:
                raise EngineModelError(f"HTTP {status} from engine model {model.id}: {e.response.text[:200]}")
        except httpx.HTTPError as e:
            last_err = EngineModelError(f"transport error calling engine model {model.id}: {e}")
        except (KeyError, IndexError, TypeError, ValueError) as e:
            last_err = EngineModelError(f"unexpected response from engine model {model.id}: {e!r}")
        if attempt < max(retries, 1):
            time.sleep(backoff * (2 ** (attempt - 1)))
    assert last_err is not None
    raise last_err


def call_engine_model(
    model: OrchModel,
    messages: list[dict],
    *,
    base_url: str = _DEFAULT_OLLAMA_URL,
    timeout: float = 60.0,
    max_tokens: int = 1024,
    temperature: float = 0.0,
    retries: int = 2,
    backoff: float = 0.5,
    think_override: bool | None = None,
) -> EngineResponse:
    """Call one engine-internal model and return its response.

    Mirrors `routism.worker.complete_full` guards (timeout, 5xx retry, 4xx fail,
    transport retry) but targets the engine registry's Ollama endpoint.

    `think_override` lets a caller FORCE thinking on/off regardless of the
    model's `thinking` registry flag. The judge/scorer (judge.py) sets it False:
    a verdict model does not need a 3-5k-token hidden reasoning trace (which
    Ollama counts against `max_tokens` and can starve the actual JSON verdict —
    see P6.C gate where thinking-on scoring returned empty content). Forcing
    thinking off makes the judge fast + cheap while still reasoning in its
    emitted JSON. When None, the model's registry `thinking` flag is used.

    PR-2: when ENGINE_SERIALIZE is on (default), the full HTTP round-trip
    (including retries and lazy pin) is held under process-wide `_ENGINE_LOCK`.
    """
    def _run() -> EngineResponse:
        # Lazy pin this tag (judge2 first pairwise; thinker/verifier if startup
        # pin was skipped or failed). Fail-open inside _pin_tag.
        _ensure_model_pinned_unlocked(model, base_url=base_url)
        return _call_engine_model_http(
            model,
            messages,
            base_url=base_url,
            timeout=timeout,
            max_tokens=max_tokens,
            temperature=temperature,
            retries=retries,
            backoff=backoff,
            think_override=think_override,
        )

    if not _engine_serialize_enabled():
        return _run()

    t0 = time.perf_counter()
    with _ENGINE_LOCK:
        wait_ms = (time.perf_counter() - t0) * 1000.0
        hold_start = time.perf_counter()
        try:
            return _run()
        finally:
            hold_ms = (time.perf_counter() - hold_start) * 1000.0
            _record_wait_hold(wait_ms, hold_ms)


def engine_models_ready(
    registry: OrchRegistry,
    *,
    base_url: str = _DEFAULT_OLLAMA_URL,
    timeout: float = 8.0,
    roles: list[str] | None = None,
) -> tuple[bool, list[str]]:
    """Probe whether required engine brains are actually pulled in Ollama.

    The registry ALWAYS yields OrchModel objects (they're hardcoded in
    orch.yaml), so a truthiness check like `thinker and verifier and judge2`
    can never detect a missing model — it only tells us the YAML has entries.
    This probe asks the Ollama server what it actually has (`/api/tags`) and
    reports whether required engine tags are present.

    ``roles``: if provided, only models with those roles are required
    (e.g. Conductor k=1 needs ``["coordinator", "verifier"]``; Parallel full
    pipeline needs all reserved models when roles is None).

    Returns (ready, missing) where `missing` lists the engine model tags that
    are NOT present among the required set. On any transport failure (Ollama
    down, unreachable), returns (False, [required tags]) so callers degrade
    gracefully instead of erroring deep inside judge/synthesize.
    """
    if roles is None:
        required = list(registry.engine_models())
    else:
        role_set = set(roles)
        required = [m for m in registry.engine_models() if m.role in role_set]
    engine_tags = [m.model for m in required]
    if not engine_tags:
        return True, []  # nothing required -> vacuously ready

    url = _ollama_root(base_url) + "/api/tags"
    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.get(url)
            resp.raise_for_status()
            data = resp.json()
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        # Ollama unreachable / bad response -> treat every required model as absent.
        return False, list(engine_tags)

    # Ollama /api/tags returns {"models": [{"name": "qwen3:1.7b", ...}, ...]}.
    # A tag without an explicit ":tag" is served as ":latest"; normalize both
    # sides so "qwen3:1.7b" matches and a bare "llama3" matches "llama3:latest".
    present: set[str] = set()
    for m in data.get("models", []) or []:
        name = m.get("name") or m.get("model") or ""
        if name:
            present.add(name)
            if ":" in name:
                present.add(name.split(":", 1)[0])  # allow bare-name match

    def _has(tag: str) -> bool:
        if tag in present:
            return True
        # a registry tag of "foo" is satisfied by a pulled "foo:latest"
        return f"{tag}:latest" in present or tag.split(":", 1)[0] in present

    missing = [t for t in engine_tags if not _has(t)]
    return (len(missing) == 0), missing


def think(
    registry: OrchRegistry | None,
    messages: list[dict],
    *,
    role: str = "coordinator",
    base_url: str = _DEFAULT_OLLAMA_URL,
    temperature: float = 0.0,
    max_tokens: int = 1024,
    timeout: float = 90.0,
) -> EngineResponse:
    """Convenience: call the engine model of a given role (default coordinator).
    Returns the EngineResponse with reasoning preserved in `.thinking`."""
    reg = registry or OrchRegistry.load(
        os.path.join(os.path.dirname(__file__), "orch.yaml")
    )
    models = reg.by_role(role)
    if not models:
        raise EngineModelError(f"no engine model with role={role!r} in orch.yaml")
    return call_engine_model(
        models[0], messages, base_url=base_url,
        temperature=temperature, max_tokens=max_tokens, timeout=timeout,
    )
