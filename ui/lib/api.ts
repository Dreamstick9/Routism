// P4.B/C/D + Phase-3 (U1-U5) — typed wrappers around the Routism backend.
// Talks to the FastAPI server on :8000 (the Phase 0/1/4A engine).
// Server endpoints used:
//  GET  /v1/management/pool           (open)
//  POST /v1/management/pool           (auth)
//  DEL  /v1/management/pool/{id}      (auth)
//  GET  /v1/management/health/{id}   (open)
//  GET  /v1/management/ollama/models  (open)
//  POST /v1/management/ollama/start   (auth)
//  GET  /v1/health                    (open, aggregate — B7)
//  GET  /v1/metrics                   (open — B4)
//  GET  /v1/settings                  (auth)
//  PUT  /v1/settings                  (auth)
//  POST /api/plan
//  GET  /v1/orch/registry             (open — P5.A: engine's own model registry)
//
// P5.A — engine-reserved models (Phase-5 learned-coordinator SLM + dedicated
// verifier) live ONLY in the orchestration engine's own registry and must NEVER
// appear as app workers. The backend tags each pool entry with `reserved: bool`
// and returns a top-level `reserved_ids: string[]` on the pool endpoint, plus a
// `GET /v1/orch/registry` exposing `{models, reserved_ids}`. The UI filters on
// these so engine models (orch-coordinator-qwen3-0.6b / orch-verifier) never show
// as selectable workers. Backend already rejects reserved ids on POST (400) —
// the UI filter is defense-in-depth + display.

export type Worker = {
  id: string;
  provider: string;
  base_url: string;
  model: string;
  tags: string[];
  api_key?: string | null;
  /** True when a key is stored server-side (secret never returned). */
  api_key_configured?: boolean;
  timeout_s?: number;
  max_tokens?: number;
  // P5.A: reserved == true marks an engine-registry model (coordinator SLM /
  // dedicated verifier) that must NEVER be offered as an app worker. Backend tags
  // each pool entry; UI filters on it. Undefined on older backends = not reserved.
  reserved?: boolean;
  // Role-pin flags. NOT part of the stored Worker — only honored on POST /pool
  // to declare this worker as the orchestrator or verifier when adding it.
  set_as_orchestrator?: boolean;
  set_as_verifier?: boolean;
};

export type PoolResponse = {
  size: number;
  capacity: 5;
  orchestrator_worker_id?: string | null;
  verifier_worker_id?: string | null;
  workers: Worker[];
  // P5.A: ids of engine-reserved models (coordinator SLM + dedicated verifier)
  // that must never be selectable as app workers. Backend guarantees this array
  // is present; treat undefined as empty for robustness against older servers.
  reserved_ids?: string[];
  /** "vault" when signed-in buyer BYOK pool; management yaml otherwise. */
  source?: "vault" | "management" | string;
  user_id?: string;
};

// P5.A — engine-reserved model filtering.
// Engine models (coordinator SLM Qwen3-0.6B + dedicated verifier) live ONLY in
// routism_orch's own registry and must NEVER appear as selectable app workers.
// `isReservedWorker` checks the per-worker `reserved` flag (authoritative when
// present), falling back to membership in the pool's `reserved_ids` array. This
// double signal covers both invariants Hermes guarantees (see Phase-5-Comms).
export function isReservedWorker(w: Worker, reservedIds?: string[]): boolean {
  if (w.reserved === true) return true;
  return Array.isArray(reservedIds) ? reservedIds.includes(w.id) : false;
}

// Returns only the user-visible (non-reserved) workers from a pool response.
// Use everywhere the UI lists "selectable" workers (Providers list, Add-Worker
// dropdowns, Settings role pickers, home dashboard list).
export function filterReservedWorkers(pool: PoolResponse | null): Worker[] {
  if (!pool) return [];
  return pool.workers.filter((w) => !isReservedWorker(w, pool.reserved_ids));
}

export type HealthResponse = {
  id: string;
  reachable: boolean;
  status_code: number | null;
  api_key_configured: boolean;
  url: string;
  error: string | null;
};

export type PlanStep = {
  worker_id: string;
  subtask: string;
  access_list: (number | string)[];
};

export type PlanTraceStep = {
  index: number;
  worker_id: string;
  subtask: string;
  access_list: (number | string)[];
  saw_prior_context: boolean;
  verified: boolean;
  verdict_reason: string;
  repaired: boolean;
  output: string;
  // P6.F: when this step is a parallel fan-out worker, the candidate + score
  // ride here on the SSE `event: step` frame (master plan §3.4). Optional so the
  // existing single-step trace renders unchanged before Hermes ships parallel.
  candidate?: ParallelCandidate;
};

// P6.F — parallel-orchestration trace shapes (forward-compatible).
// Hermes ships these as extra fields on the existing SSE `event: step` frame
// and on /api/plan steps (master plan §3.2 / §3.4). Until Hermes signals the
// parallel endpoints live (Phase-6-Comms.md), every field below is OPTIONAL so
// the existing single-step trace renders unchanged; the UI lights up the
// parallel cards the moment Hermes starts emitting them.

// One worker's candidate answer from the parallel fan-out + its engine scores.
export type ParallelCandidate = {
  // worker id that produced this answer (one of the user's 4 workers)
  worker_id: string;
  // per-worker role prompt the engine assigned ("answer concisely", "show reasoning", ...)
  role?: string;
  answer: string;
  // absolute score from eng-verifier (0-10)
  score?: number;
  // short reason for the score
  score_reason?: string;
  // true when this worker failed/timed out and contributed no answer
  error?: string | null;
  elapsed_ms?: number;
};

// Pairwise A/B cross-check from eng-judge2 on the top-2 candidates.
export type PairwiseCheck = {
  winner: string; // worker_id
  loser: string; // worker_id
  reason?: string;
};

// Engine-internal synthesis step that produced (or refined) the FINAL.
export type SynthesisTrace = {
  engine: "eng-thinker" | string;
  strategy?: string;
  // which candidate workers the synthesizer merged
  contributors: string[];
  // synthesized text BEFORE the final verify gate
  draft: string;
};

// Parallel orchestration summary, present once on the run/plan payload when the
// engine ran a parallel fan-out (master plan §2). Absent for trivial queries
// and for P5 single-select routing.
export type ParallelTrace = {
  fan_out: ParallelCandidate[];
  pairwise?: PairwiseCheck[];
  synthesis?: SynthesisTrace;
  // FINAL after the verify gate (eng-verifier accept / 1 retry)
  final?: string;
  used_fallback?: boolean;
};

export type PlanResponse = {
  mode: "trivial" | "complex";
  degraded?: boolean;
  pool: string[];
  plan: PlanStep[];
  steps: PlanTraceStep[];
  answer: string;
  // P6.F: parallel candidate + score trace (present once Hermes ships the
  // parallel engine on POST /api/plan). Undefined on the current P5 single-select
  // backend so the blocking Plan view stays forward-compatible.
  parallel?: ParallelTrace;
  orchestration_input_tokens: number;
  orchestration_output_tokens: number;
  worker_prompt_tokens?: number;
  worker_completion_tokens?: number;
  total_tokens?: number;
  budget_hit: boolean;
};

// B7: GET /v1/health — aggregate reachability probe for the whole pool in one call.
export type HealthSummary = {
  id: string;
  reachable: boolean;
  status_code: number | null;
  api_key_configured: boolean;
  url: string;
  error: string | null;
};

export type HealthAllResponse = {
  workers: HealthSummary[];
  generated_at: number;
};

// B4: GET /v1/metrics — pool size/capacity, orchestrator/verifier ids, last Phase-2
// eval (accuracy / token overhead / win-loss) when present.
export type MetricsPool = {
  size: number;
  capacity: number;
  orchestrator_worker_id: string | null;
  verifier_worker_id: string | null;
  workers: string[];
} | null;

// phase2_results.json shape (subset the dashboard reads). All fields optional
// because the file may be absent or partially populated.
export type MetricsEval = {
  routism?: {
    accuracy?: number;
    input_tokens?: number;
    output_tokens?: number;
    latency_ms?: number;
    wins?: number;
    losses?: number;
    ties?: number;
    ok?: number;
    total?: number;
  };
  zero_router?: {
    accuracy?: number;
    input_tokens?: number;
    output_tokens?: number;
    latency_ms?: number;
  };
  overhead_ratio?: number;
  verdict?: string;
  generated_at?: string;
  records?: Array<{
    task_id: string;
    query: string;
    system_name: string;
    answer: string;
    input_tokens: number;
    output_tokens: number;
    latency_ms: number;
    ok: boolean;
    error: string | null;
  }>;
  [key: string]: unknown;
} | null;

export type MetricsResponse = {
  pool: MetricsPool;
  eval: MetricsEval;
  /** Last Conductor run worker ids (from trajectory log). */
  models_used?: string[];
  trajectory?: {
    models_used?: string[];
    run_id?: string | null;
    logged_at?: number | null;
    enabled?: boolean;
  };
  engine?: Record<string, number>;
  billing?: Record<string, unknown>;
  generated_at: number;
};

// U5: GET/PUT /v1/settings — global orchestrator settings.
// Per HERMES [00:10], GET returns + PUT accepts orchestrator_worker_id and
// verifier_worker_id (validated against the pool, 400 on unknown). These are the
// "pin the conductor/verifier" controls surfaced as dropdowns on the Settings
// page, populated from getPool().
export type Settings = {
  max_repairs: number;
  max_total_tokens: number;
  memory_backend: string;
  memory_scope: string;
  orchestrator_worker_id?: string | null;
  verifier_worker_id?: string | null;
};

export type SettingsUpdate = {
  max_repairs?: number;
  max_total_tokens?: number;
  memory_backend?: string;
  memory_scope?: string;
  orchestrator_worker_id?: string | null;
  verifier_worker_id?: string | null;
};

// Browser → API. In Docker Compose the UI is :3000 and the API is :8000 on the host.
// Baked in at build time via NEXT_PUBLIC_ROUTISM_API (see ui/Dockerfile + compose).
const API_BASE = (
  process.env.NEXT_PUBLIC_ROUTISM_API || "http://localhost:8000"
).replace(/\/$/, "");

async function jfetch<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(`${API_BASE}${path}`, {
    ...init,
    credentials: "include",
    headers: { "content-type": "application/json", ...(init?.headers ?? {}) },
    cache: "no-store",
  });
  if (!r.ok) {
    let detail: string | undefined;
    try {
      const j = await r.json();
      detail = typeof j?.detail === "string" ? j.detail : JSON.stringify(j);
    } catch {
      detail = await r.text();
    }
    throw new Error(`${r.status} ${r.statusText}: ${detail ?? ""}`.trim());
  }
  return (await r.json()) as T;
}

export function getApiBase(): string {
  return API_BASE;
}

export async function getPool(): Promise<PoolResponse> {
  return jfetch<PoolResponse>("/v1/management/pool");
}

export async function addWorker(w: Worker): Promise<{ ok: boolean; size: number; id: string }> {
  return jfetch("/v1/management/pool", {
    method: "POST",
    body: JSON.stringify(w),
  });
}

export async function removeWorker(id: string): Promise<{ ok: boolean; size: number; removed: string }> {
  return jfetch(`/v1/management/pool/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });
}

export async function getHealth(id: string): Promise<HealthResponse> {
  return jfetch<HealthResponse>(`/v1/management/health/${encodeURIComponent(id)}`);
}

export type OllamaModelsResponse = {
  running: boolean;
  base_url?: string;
  openai_base_url?: string;
  models?: string[];
  provider?: string;
  error?: string;
};

/** Alias used for all local one-click providers (Ollama / LM Studio / MLX). */
export type LocalModelsResponse = OllamaModelsResponse;

export async function getOllamaModels(): Promise<OllamaModelsResponse> {
  return jfetch<OllamaModelsResponse>("/v1/management/ollama/models");
}

/** Discover models from a local one-click provider: ollama | lmstudio | mlx.
 *  Optional ``baseUrl`` overrides host/port (e.g. ``http://localhost:6969`` or ``6969``).
 *  Optional ``apiKey`` for local servers that require Bearer auth.
 */
export async function getLocalProviderModels(
  provider: "ollama" | "lmstudio" | "mlx" | string,
  baseUrl?: string | null,
  apiKey?: string | null,
): Promise<LocalModelsResponse> {
  const id = encodeURIComponent(provider);
  const params = new URLSearchParams();
  if (baseUrl && baseUrl.trim()) params.set("base_url", baseUrl.trim());
  if (apiKey && apiKey.trim()) params.set("api_key", apiKey.trim());
  const q = params.toString() ? `?${params.toString()}` : "";
  return jfetch<LocalModelsResponse>(`/v1/management/local/${id}/models${q}`);
}

// P5.A: GET /v1/orch/registry — the orchestration engine's OWN model registry.
// Returns the coordinator SLM + any dedicated verifier plus the reserved_ids
// list. Engine models must NEVER appear as app workers; the UI uses this (and
// the per-worker `reserved` flag on /v1/management/pool) to hide them from
// Add-Worker / Providers. Optional dependency — if the endpoint is absent on an
// older backend, the caller falls back to pool.reserved_ids / worker.reserved.
export type OrchRegistryModel = {
  id: string;
  provider?: string;
  model?: string;
  reserved?: boolean;
  role?: string;
};

export type OrchRegistryResponse = {
  models: OrchRegistryModel[];
  reserved_ids: string[];
};

export async function getOrchRegistry(): Promise<OrchRegistryResponse> {
  return jfetch<OrchRegistryResponse>("/v1/orch/registry");
}

// Fetch the engine's reserved_ids. Best-effort: if the engine endpoint is
// unavailable (older backend / engine not loaded), resolves to [] so callers
// can safely spread it into a Set lookup. Prefer the per-worker `reserved` flag
// from getPool() when available; this is a fallback for places that only have
// model id strings (e.g. the Ollama model picker).
export async function getReservedIds(): Promise<string[]> {
  try {
    const r = await getOrchRegistry();
    return r.reserved_ids ?? [];
  } catch {
    return [];
  }
}

function localWorkerId(provider: string, model: string): string {
  const safe = model.replace(/[^a-zA-Z0-9_.-]/g, "_").replace(/[.-]/g, "_");
  return `${provider}_${safe}`;
}

export type AddLocalModelResult = {
  ok: boolean;
  size: number;
  id: string;
  /** Non-fatal warm-start warning (Ollama only). */
  warning?: string;
};

// POST a selected Ollama model as a worker into the pool, then load it into
// Ollama memory (the ONLY moment a model is started — after the user picks it).
export async function addOllamaModel(
  model: string,
  baseUrl?: string,
): Promise<AddLocalModelResult> {
  return addLocalModel("ollama", model, baseUrl ?? "http://localhost:11434/v1");
}

/** Normalize any provider base to an OpenAI-compatible API root (no chat path). */
export function normalizeOpenAIBaseUrl(input: string | null | undefined): string {
  let raw = (input || "").trim();
  if (!raw) return "";
  raw = raw.replace(/\/+$/, "");
  // Repair catalog/copy-paste mistakes that store the chat URL as base
  if (raw.includes("/chat/completions")) {
    raw = raw.split("/chat/completions")[0].replace(/\/+$/, "");
  }
  if (raw.endsWith("/models")) {
    raw = raw.slice(0, -"/models".length).replace(/\/+$/, "");
  }
  return raw;
}

/** Normalize user host input to an OpenAI-compatible …/v1 base URL. */
export function normalizeLocalOpenAIBase(input: string | null | undefined, fallback: string): string {
  let raw = (input || "").trim();
  if (!raw) raw = fallback;
  if (raw.startsWith(":") && /^\d+$/.test(raw.slice(1))) raw = `http://localhost${raw}`;
  else if (/^\d+$/.test(raw)) raw = `http://localhost:${raw}`;
  else if (!raw.includes("://")) raw = `http://${raw}`;
  raw = normalizeOpenAIBaseUrl(raw);
  if (!raw.endsWith("/v1")) raw = `${raw}/v1`;
  return raw;
}

/**
 * Add a local one-click provider model to the pool.
 * Ollama additionally warm-loads via /ollama/start (best-effort; add still succeeds).
 */
export async function addLocalModel(
  provider: "ollama" | "lmstudio" | "mlx" | string,
  model: string,
  baseUrl?: string,
  apiKey?: string | null,
): Promise<AddLocalModelResult> {
  const defaults: Record<string, { base: string; tags: string[] }> = {
    ollama: { base: "http://localhost:11434/v1", tags: ["local", "ollama", "free"] },
    lmstudio: { base: "http://localhost:1234/v1", tags: ["local", "lmstudio", "free"] },
    mlx: { base: "http://localhost:6969/v1", tags: ["local", "mlx", "free"] },
  };
  const conf = defaults[provider] ?? {
    base: baseUrl || "http://localhost/v1",
    tags: ["local", provider, "free"],
  };
  const resolvedBase = normalizeLocalOpenAIBase(baseUrl, conf.base);
  const id = localWorkerId(provider, model);
  const worker: Worker = {
    id,
    provider,
    base_url: resolvedBase,
    model,
    tags: conf.tags,
    api_key: apiKey && apiKey.trim() ? apiKey.trim() : undefined,
  };
  // Routes to /v1/vault when buyer is signed in; management pool otherwise.
  const res = await addWorker(worker);

  let warning: string | undefined;
  if (provider === "ollama") {
    // Warm-load is best-effort: pool add already succeeded; surface start errors.
    try {
      const start = await jfetch<{ ok?: boolean; error?: string; status_code?: number }>(
        "/v1/management/ollama/start",
        {
          method: "POST",
          body: JSON.stringify({ model }),
        },
      );
      if (start && start.ok === false) {
        warning =
          start.error ||
          `Ollama could not warm-load ${model}` +
            (start.status_code != null ? ` (HTTP ${start.status_code})` : "");
      }
    } catch (e) {
      warning = e instanceof Error ? e.message : String(e);
    }
  }
  return warning ? { ...res, warning } : res;
}

export async function runPlan(
  query: string,
  mode: "auto" | "parallel" | "conductor" = "conductor",
): Promise<PlanResponse | { error: string }> {
  // /api/plan returns 200 even on orchestration errors with {error:...}; handle both shapes.
  type MaybeErr = PlanResponse | { error: string };
  const data = await jfetch<MaybeErr>("/api/plan", {
    method: "POST",
    body: JSON.stringify({
      model: "routism-ultra",
      messages: [{ role: "user", content: query }],
      mode,
    }),
  });
  return data;
}

// ── Streaming run (SSE) — POST /v1/run ──────────────────────────────────────
// Emits events as the executor runs so the Plan page can show step cards pop in
// live instead of waiting for one blocking /api/plan call.
export type RunMetaEvent = {
  mode: "trivial" | "complex";
  degraded: boolean;
  pool: string[];
  // P6.F: true when the engine is running a parallel fan-out for this query
  // (master plan §2). Undefined on the P5 single-select backend so the
  // Orchestration view degrades to the single-step layout before Hermes ships.
  parallel?: boolean;
  // Conductor Mode extras (7D) — optional, ignored by pure-parallel runs.
  orchestration?: "conductor" | "conductor_degraded" | "parallel" | string;
  dag_layers?: number;
  dag_subtasks?: number;
  missing_engine_models?: string[];
  /** Machine-readable why degraded (e.g. engine_unavailable, no_workers). */
  degraded_reason?: string;
};
export type RunDoneEvent = {
  answer: string;
  usage: {
    orchestration_input_tokens: number;
    orchestration_output_tokens: number;
    worker_prompt_tokens: number;
    worker_completion_tokens: number;
    total_tokens: number;
  };
  degraded: boolean;
  budget_hit: boolean;
  degraded_reason?: string;
  missing_engine_models?: string[];
  /** Some DAG nodes failed while others succeeded. */
  partial_success?: boolean;
  // P6.F: parallel candidate + score trace shipped by Hermes on the SSE
  // `event: done` frame once the parallel engine is live (master plan §3.2 /
  // §3.4). Undefined on the P5 single-select backend so the streaming Plan view
  // stays forward-compatible.
  parallel?: ParallelTrace & {
    conductor?: {
      layers?: string[][];
      subtasks?: ConductorSubtask[];
    };
  };
};

// PR-5 — Conductor DAG SSE shapes (backend already emits these; UI must handle).
export type ConductorSubtask = {
  id: string;
  prompt: string;
  tags?: string[];
  depends_on?: string[];
  critical?: boolean;
  assigned_worker?: string | null;
  assigned_workers?: string[];
  assignment_reason?: string | null;
  selected_worker_id?: string | null;
  result?: string | null;
  error?: string | null;
  elapsed_ms?: number | null;
  samples?: Array<{
    worker_id: string;
    answer?: string | null;
    error?: string | null;
    score?: number | null;
    sample_index?: number;
  }>;
};

export type ConductorPlanEvent = {
  query?: string;
  layers?: number;
  subtasks?: number;
  /** Full connected worker pool (same as meta.pool) so roster never undercounts. */
  pool?: string[];
  plan?: {
    query?: string;
    layers?: string[][];
    subtasks?: ConductorSubtask[];
  };
};

export type DagLayerStartEvent = {
  layer: number;
  subtask_ids: string[];
};

export type DagLayerCompleteEvent = {
  layer: number;
  elapsed_ms?: number;
  subtask_count?: number;
  mean_score?: number;
};

export type KSamplePickEvent = {
  subtask_id: string;
  winner?: string | null;
  losers?: string[];
  method?: string;
  scores?: Array<{
    worker_id: string;
    score?: number | null;
    sample_index?: number;
  }>;
};

/** PR-7 — Bounded replan when a layer's mean score falls below the floor. */
export type ReplanEvent = {
  layer: number;
  mean_score?: number;
  reason?: string;
  new_subtask_ids?: string[];
};

export type RunStreamHandlers = {
  onMeta?: (m: RunMetaEvent) => void;
  onStep?: (s: PlanTraceStep) => void;
  onDone?: (d: RunDoneEvent) => void;
  onError?: (message: string) => void;
  // P6.F: parallel-specific SSE events Hermes emits during a fan-out run
  // (master plan §4). These fire between meta and done once the parallel engine
  // is live. Undefined handlers just skip — the streaming Page stays
  // forward-compatible with the P5 single-select backend.
  onFanOut?: (plan: { workers: string[]; roles?: Record<string, string> }) => void;
  onCandidate?: (candidate: ParallelCandidate) => void;
  onScore?: (scores: { worker_id: string; score: number; reason: string }[]) => void;
  onSynthesis?: (s: SynthesisTrace) => void;
  // PR-5: Conductor DAG — must not be silently dropped
  onConductorPlan?: (p: ConductorPlanEvent) => void;
  onDagLayerStart?: (e: DagLayerStartEvent) => void;
  onDagLayerComplete?: (e: DagLayerCompleteEvent) => void;
  onKSamplePick?: (e: KSamplePickEvent) => void;
  // PR-7: bounded replan of remaining subgraph
  onReplan?: (e: ReplanEvent) => void;
};

/** Events the client is required to route (PR-5 / PR-7 contract). */
export const RUN_STREAM_EVENT_KINDS = [
  "meta",
  "step",
  "fan_out",
  "scores",
  "synthesis",
  "done",
  "error",
  "conductor_plan",
  "dag_layer_start",
  "dag_layer_complete",
  "k_sample_pick",
  "replan",
] as const;

export type RunStreamEventKind = (typeof RUN_STREAM_EVENT_KINDS)[number];

/**
 * Route one SSE event to handlers. Pure dispatch used by runPlanStream and tests.
 * Returns true if the event kind is recognized (handler may still be undefined).
 */
export function routeRunStreamEvent(
  event: string,
  parsed: unknown,
  handlers: RunStreamHandlers,
): boolean {
  if (event === "meta") {
    handlers.onMeta?.(parsed as RunMetaEvent);
    return true;
  }
  if (event === "step") {
    const s = parsed as PlanTraceStep;
    handlers.onStep?.(s);
    if (s.candidate) handlers.onCandidate?.(s.candidate);
    return true;
  }
  if (event === "fan_out") {
    handlers.onFanOut?.(
      parsed as { workers: string[]; roles?: Record<string, string> },
    );
    return true;
  }
  if (event === "scores") {
    const raw = parsed as
      | { worker_id: string; score: number; reason: string }[]
      | { data?: { worker_id: string; score: number; reason: string }[] };
    const list = Array.isArray(raw)
      ? raw
      : Array.isArray(raw?.data)
        ? raw.data
        : [];
    handlers.onScore?.(list);
    return true;
  }
  if (event === "synthesis") {
    handlers.onSynthesis?.(parsed as SynthesisTrace);
    return true;
  }
  if (event === "done") {
    handlers.onDone?.(parsed as RunDoneEvent);
    return true;
  }
  if (event === "error") {
    handlers.onError?.((parsed as { message: string }).message);
    return true;
  }
  if (event === "conductor_plan") {
    handlers.onConductorPlan?.(parsed as ConductorPlanEvent);
    return true;
  }
  if (event === "dag_layer_start") {
    handlers.onDagLayerStart?.(parsed as DagLayerStartEvent);
    return true;
  }
  if (event === "dag_layer_complete") {
    handlers.onDagLayerComplete?.(parsed as DagLayerCompleteEvent);
    return true;
  }
  if (event === "k_sample_pick") {
    handlers.onKSamplePick?.(parsed as KSamplePickEvent);
    return true;
  }
  if (event === "replan") {
    handlers.onReplan?.(parsed as ReplanEvent);
    return true;
  }
  return false;
}

// Consume the SSE stream. Resolves when the stream closes. Parses `event:`/`data:`
// framed messages from the ReadableStream. Pass an AbortSignal to cancel.
export async function runPlanStream(
  query: string,
  handlers: RunStreamHandlers,
  signal?: AbortSignal,
  mode: "auto" | "parallel" | "conductor" = "conductor",
): Promise<void> {
  // Product is Conductor-only; coerce legacy parallel/auto to conductor.
  const resolvedMode = mode === "conductor" ? "conductor" : "conductor";
  const r = await fetch(`${API_BASE}/v1/run`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      model: "routism-ultra",
      messages: [{ role: "user", content: query }],
      mode: resolvedMode,
    }),
    signal,
  });
  if (!r.ok || !r.body) {
    handlers.onError?.(`${r.status} ${r.statusText}`);
    return;
  }
  const reader = r.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  const dispatch = (block: string) => {
    let event = "message";
    let data = "";
    for (const line of block.split("\n")) {
      if (line.startsWith("event:")) event = line.slice(6).trim();
      else if (line.startsWith("data:")) data += line.slice(5).trim();
    }
    if (!data) return;
    let parsed: unknown;
    try {
      parsed = JSON.parse(data);
    } catch {
      return;
    }
    routeRunStreamEvent(event, parsed, handlers);
  };
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    let idx: number;
    while ((idx = buf.indexOf("\n\n")) !== -1) {
      const block = buf.slice(0, idx);
      buf = buf.slice(idx + 2);
      if (block.trim()) dispatch(block);
    }
  }
  if (buf.trim()) dispatch(buf);
}

// B7: aggregate reachability probe for the whole pool in ONE call.
export async function getHealthAll(): Promise<HealthAllResponse> {
  return jfetch<HealthAllResponse>("/v1/health");
}

// B4: observability for the dashboard's Metrics page.
export async function getMetrics(): Promise<MetricsResponse> {
  return jfetch<MetricsResponse>("/v1/metrics");
}

// ── Benchmarks (NORTHSTAR eval harness UI) ───────────────────────────────
export type BenchmarkSeed = {
  id: string;
  name: string;
  path: string;
  description: string;
  n_tasks?: number | null;
  exists?: boolean;
};

export type BenchmarkSummary = {
  kind?: string;
  created_at?: string;
  seed?: { n_tasks?: number; task_ids?: string[] };
  worker_ids?: string[];
  models?: Record<string, string>;
  SHIP?: string | boolean;
  win_rate?: number;
  mean_delta?: number;
  mean_conductor_score?: number;
  mean_max_worker_score?: number;
  metrics?: Record<string, unknown>;
  mean_scores?: Record<string, number | null | undefined>;
  rows?: Array<{
    task_id?: string;
    category?: string;
    worker_scores?: Record<string, number>;
    conductor?: number;
    conductor_score?: number;
    max_solo?: number;
    winner?: string;
    delta?: number;
    models_used?: string[];
  }>;
  n_tasks?: number;
};

export type BenchmarkStatus = {
  id: string | null;
  status: "idle" | "running" | "done" | "error" | string;
  started_at?: string | null;
  finished_at?: string | null;
  params?: Record<string, unknown> | null;
  log: string[];
  progress?: string;
  result_path?: string | null;
  error?: string | null;
  summary?: BenchmarkSummary | null;
};

export type BenchmarkResultMeta = {
  name: string;
  path: string;
  size_bytes: number;
  mtime: string;
  SHIP?: string | boolean;
  win_rate?: number;
  mean_delta?: number;
  kind?: string;
  n_tasks?: number;
  worker_ids?: string[];
};

export async function listBenchmarkSeeds(): Promise<{ seeds: BenchmarkSeed[] }> {
  return jfetch("/v1/benchmarks/seeds");
}

export async function getBenchmarkStatus(): Promise<BenchmarkStatus> {
  return jfetch("/v1/benchmarks/status");
}

export async function listBenchmarkResults(): Promise<{ results: BenchmarkResultMeta[] }> {
  return jfetch("/v1/benchmarks/results");
}

export async function getBenchmarkResult(
  name: string,
): Promise<{ name: string; path: string; summary: BenchmarkSummary; payload: unknown }> {
  return jfetch(`/v1/benchmarks/results/${encodeURIComponent(name)}`);
}

export async function startBenchmarkRun(body: {
  seed?: string;
  mode?: string;
  limit?: number | null;
  timeout_s?: number;
}): Promise<{ ok: boolean; id: string; status: string }> {
  return jfetch("/v1/benchmarks/run", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

// U5: read global settings. Calls /v1/settings which is management-auth-gated;
// on loopback without MANAGEMENT_API_KEY set it succeeds (per HERMES [22:10]).
export async function getSettings(): Promise<Settings> {
  return jfetch<Settings>("/v1/settings");
}

// U5: update global settings. Partial body — only sent fields override.
export async function putSettings(patch: SettingsUpdate): Promise<{ ok: boolean }> {
  return jfetch<{ ok: boolean }>("/v1/settings", {
    method: "PUT",
    body: JSON.stringify(patch),
  });
}

// ── Fetch provider models ────────────────────────────────────────────────
export async function fetchProviderModels(
  baseUrl: string,
  apiKey?: string | null,
  modelsUrl?: string | null,
): Promise<{ models: string[]; error?: string }> {
  return jfetch("/v1/management/fetch-models", {
    method: "POST",
    body: JSON.stringify({
      base_url: baseUrl,
      api_key: apiKey || null,
      models_url: modelsUrl || null,
    }),
  });
}
