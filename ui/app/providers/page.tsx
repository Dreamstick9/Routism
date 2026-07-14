"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import {
  getPool,
  addWorker,
  removeWorker,
  getHealth,
  getLocalProviderModels,
  addLocalModel,
  getHealthAll,
  getReservedIds,
  isReservedWorker,
  filterReservedWorkers,
  fetchProviderModels,
  type Worker,
  type PoolResponse,
  type HealthSummary,
  type LocalModelsResponse,
} from "@/lib/api";
import {
  Skeleton,
  StatusDot,
  Badge,
  EmptyState,
  ErrorState,
  PageHeader,
} from "../_components/status";
import CopyButton from "../_components/copy-button";
import { type ProviderInfo, sortedProviders, NO_FETCH_PROVIDERS } from "@/lib/providers";

const CAPACITY = 5;

// Build a quick lookup from the providers list
const SORTED = sortedProviders();


type HealthByWorker = Record<string, HealthSummary | "loading" | undefined>;

export default function ProvidersPage() {
  const [pool, setPool] = useState<PoolResponse | null>(null);
  const [health, setHealth] = useState<HealthByWorker>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reservedIds, setReservedIds] = useState<string[]>([]);

  // ── Provider selection state ──────────────────────────────────────────
  const [selectedProvider, setSelectedProvider] = useState<ProviderInfo | null>(null);
  const [apiKeyInput, setApiKeyInput] = useState("");
  const [fetchedModels, setFetchedModels] = useState<string[] | null>(null);
  const [fetchingModels, setFetchingModels] = useState(false);
  const [fetchError, setFetchError] = useState<string | null>(null);
  const [selectedModel, setSelectedModel] = useState("");
  const [workerId, setWorkerId] = useState("");

  // ── Custom provider form state ────────────────────────────────────────
  const [showCustom, setShowCustom] = useState(false);
  const [customForm, setCustomForm] = useState<Worker>({
    id: "", provider: "custom", base_url: "", model: "", tags: [], api_key: "",
  });

  const [adding, setAdding] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const p = await getPool();
      setPool(p);
      setReservedIds(p.reserved_ids ?? []);
      getReservedIds().then(setReservedIds).catch(() => {});
      getHealthAll()
        .then((h) => {
          setHealth((prev) => {
            const next: HealthByWorker = { ...prev };
            for (const w of h.workers) next[w.id] = w;
            return next;
          });
        })
        .catch(() => {});
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  // Auto-fetch models when provider changes (like Hermes two-stage picker)
  useEffect(() => {
    setApiKeyInput("");
    setFetchedModels(null);
    setFetchError(null);
    setSelectedModel("");
    setWorkerId("");

    if (selectedProvider && !NO_FETCH_PROVIDERS.has(selectedProvider.id)) {
      setFetchingModels(true);
      onFetchModels();
    }
  }, [selectedProvider]);

  type LocalKind = "ollama" | "lmstudio" | "mlx";
  type LocalPanel = {
    kind: LocalKind;
    discover: LocalModelsResponse | null;
    loading: boolean;
    error: string | null;
    connecting: boolean;
    warning: string | null;
    success: string | null;
    /** User-editable host/port (persisted in localStorage). */
    hostInput: string;
    /** Optional Bearer key for local servers that require auth (e.g. some oMLX). */
    apiKeyInput: string;
    /** Models already added this session — stay highlighted; list is not cleared. */
    addedModels: string[];
    /** Collapsed card body (header always visible). */
    collapsed: boolean;
  };

  const LOCAL_META: Record<
    LocalKind,
    { title: string; blurb: string; defaultHost: string; button: string }
  > = {
    ollama: {
      title: "Ollama",
      blurb: "Discover models on this machine and add one to your pool.",
      defaultHost: "http://localhost:11434",
      button: "Connect Ollama",
    },
    lmstudio: {
      title: "LM Studio",
      blurb: "OpenAI-compatible local server. Start the server in LM Studio first.",
      defaultHost: "http://localhost:1234",
      button: "Connect LM Studio",
    },
    mlx: {
      title: "MLX / oMLX",
      blurb: "Local MLX OpenAI-compatible server (port varies — set yours below).",
      defaultHost: "http://localhost:6969",
      button: "Connect MLX",
    },
  };

  const HOST_STORAGE_KEY = "routism.localHosts.v1";
  const COLLAPSE_STORAGE_KEY = "routism.providersCollapse.v1";

  function loadStoredHosts(): Partial<Record<LocalKind, string>> {
    if (typeof window === "undefined") return {};
    try {
      const raw = localStorage.getItem(HOST_STORAGE_KEY);
      if (!raw) return {};
      const parsed = JSON.parse(raw) as Record<string, string>;
      return parsed && typeof parsed === "object" ? parsed : {};
    } catch {
      return {};
    }
  }

  function saveStoredHost(kind: LocalKind, host: string) {
    if (typeof window === "undefined") return;
    try {
      const cur = loadStoredHosts();
      cur[kind] = host;
      localStorage.setItem(HOST_STORAGE_KEY, JSON.stringify(cur));
    } catch {
      /* ignore quota */
    }
  }

  function loadCollapse(): Record<string, boolean> {
    if (typeof window === "undefined") return {};
    try {
      const raw = localStorage.getItem(COLLAPSE_STORAGE_KEY);
      return raw ? (JSON.parse(raw) as Record<string, boolean>) : {};
    } catch {
      return {};
    }
  }

  function saveCollapse(map: Record<string, boolean>) {
    if (typeof window === "undefined") return;
    try {
      localStorage.setItem(COLLAPSE_STORAGE_KEY, JSON.stringify(map));
    } catch {
      /* ignore */
    }
  }

  const emptyLocal = (
    kind: LocalKind,
    host?: string,
    collapsed = false,
  ): LocalPanel => ({
    kind,
    discover: null,
    loading: false,
    error: null,
    connecting: false,
    warning: null,
    success: null,
    hostInput: host ?? LOCAL_META[kind].defaultHost,
    apiKeyInput: "",
    addedModels: [],
    collapsed,
  });

  // Defaults only on first paint (server + client match); hydrate from localStorage after mount.
  const [localPanels, setLocalPanels] = useState<Record<LocalKind, LocalPanel>>(() => ({
    ollama: emptyLocal("ollama", LOCAL_META.ollama.defaultHost, false),
    lmstudio: emptyLocal("lmstudio", LOCAL_META.lmstudio.defaultHost, false),
    mlx: emptyLocal("mlx", "http://localhost:6969", false),
  }));

  // Section collapse for non-local blocks
  const [sectionCollapse, setSectionCollapse] = useState<Record<string, boolean>>({
    cloud: false,
    pool: false,
  });

  useEffect(() => {
    const stored = loadStoredHosts();
    const col = loadCollapse();
    setLocalPanels({
      ollama: emptyLocal("ollama", stored.ollama, !!col.ollama),
      lmstudio: emptyLocal(
        "lmstudio",
        stored.lmstudio,
        col.lmstudio !== false ? !!col.lmstudio : false,
      ),
      mlx: emptyLocal("mlx", stored.mlx ?? "http://localhost:6969", !!col.mlx),
    });
    setSectionCollapse({
      cloud: !!col.cloud,
      pool: col.pool === undefined ? false : !!col.pool,
    });
  }, []);

  function toggleSection(id: string) {
    setSectionCollapse((prev) => {
      const next = { ...prev, [id]: !prev[id] };
      saveCollapse({ ...loadCollapse(), ...next });
      return next;
    });
  }

  function patchLocal(kind: LocalKind, patch: Partial<LocalPanel>) {
    setLocalPanels((prev) => ({ ...prev, [kind]: { ...prev[kind], ...patch } }));
  }

  function toggleLocalCollapse(kind: LocalKind) {
    setLocalPanels((prev) => {
      const nextCollapsed = !prev[kind].collapsed;
      const next = {
        ...prev,
        [kind]: { ...prev[kind], collapsed: nextCollapsed },
      };
      saveCollapse({
        ...loadCollapse(),
        [kind]: nextCollapsed,
        cloud: sectionCollapse.cloud,
        pool: sectionCollapse.pool,
      });
      return next;
    });
  }

  function setLocalHost(kind: LocalKind, value: string) {
    // Do not wipe a successful discover just because the user is typing —
    // only clear error. Re-run Connect after host change to refresh models.
    patchLocal(kind, { hostInput: value, error: null, success: null });
    saveStoredHost(kind, value);
  }

  async function onConnectLocal(kind: LocalKind) {
    const host = localPanels[kind].hostInput.trim() || LOCAL_META[kind].defaultHost;
    const key = localPanels[kind].apiKeyInput.trim();
    saveStoredHost(kind, host);
    patchLocal(kind, {
      error: null,
      warning: null,
      success: null,
      loading: true,
      hostInput: host,
      collapsed: false,
    });
    try {
      const res = await getLocalProviderModels(kind, host, key || null);
      patchLocal(kind, {
        discover: res,
        loading: false,
        // Keep previous addedModels — reconnect does not reset “already in pool”
        error: res.running
          ? null
          : (res.error ??
            `${LOCAL_META[kind].title} is not running at ${host}. Check host/port.`),
      });
    } catch (e) {
      patchLocal(kind, {
        loading: false,
        error: e instanceof Error ? e.message : String(e),
        // Keep last good discover if any so UI does not blank on transient errors
      });
    }
  }

  async function onPickLocal(kind: LocalKind, model: string) {
    patchLocal(kind, { connecting: true, error: null, warning: null, success: null });
    try {
      const panel = localPanels[kind];
      const base =
        panel.discover?.openai_base_url ||
        panel.discover?.base_url ||
        panel.hostInput;
      const key = panel.apiKeyInput.trim();
      if (
        (kind === "mlx" || kind === "lmstudio") &&
        !key &&
        panel.discover?.error?.includes("401")
      ) {
        // soft guidance only
      }
      const res = await addLocalModel(kind, model, base, key || null);
      // Keep discover open so user can add more models without re-connecting.
      patchLocal(kind, {
        connecting: false,
        warning: res.warning ?? null,
        success: `Added “${model}” to pool as ${res.id}`,
        addedModels: Array.from(new Set([...(panel.addedModels || []), model])),
      });
      await refresh();
    } catch (e) {
      patchLocal(kind, {
        connecting: false,
        // Do NOT clear discover / model list on failure
        error: e instanceof Error ? e.message : String(e),
      });
    }
  }

  const visibleWorkers = filterReservedWorkers(pool);
  const size = visibleWorkers.length;
  const full = size >= CAPACITY;

  // ── Fetch models from provider's API ──────────────────────────────────
  async function onFetchModels() {
    const prov = selectedProvider;
    if (!prov) return;
    setFetchingModels(true);
    setFetchError(null);
    try {
      const result = await fetchProviderModels(prov.baseUrl, apiKeyInput || null, prov.modelsUrl || null);
      if (result.error) {
        // Non-2xx (401/403/404/…) — never treat as success. Fall back to known models
        // for picking only when we have a static list; still show the real error.
        setFetchedModels(prov.knownModels.length > 0 ? prov.knownModels : []);
        const is401 = /401|unauthorized/i.test(result.error);
        const is404 = /404|not found/i.test(result.error);
        let message: string;
        if (is401) {
          message = `Unauthorized (401) — enter a valid ${prov.name} API key and click ↻ Refresh. Live fetch failed; not connected yet.`;
        } else if (is404) {
          message = `Not found (404) — models endpoint missing or wrong base URL for ${prov.name}. ${result.error}`;
        } else {
          message = `Could not fetch live models: ${result.error}`;
        }
        setFetchError(message);
      } else if (result.models.length === 0) {
        setFetchedModels(prov.knownModels.length > 0 ? prov.knownModels : []);
        if (prov.knownModels.length > 0) {
          setFetchError("Provider returned no models. Showing known model list.");
        } else {
          setFetchError("No models found. Try entering a model name manually.");
        }
      } else {
        setFetchedModels(result.models);
      }
    } catch (e) {
      setFetchedModels(selectedProvider!.knownModels.length > 0 ? selectedProvider!.knownModels : []);
      setFetchError(e instanceof Error ? e.message : String(e));
    } finally {
      setFetchingModels(false);
    }
  }

  // ── Add a provider worker ─────────────────────────────────────────────
  async function onAdd() {
    setFormError(null);

    const id = selectedProvider ? workerId.trim() || selectedProvider.id : customForm.id.trim();
    const baseUrl = selectedProvider ? selectedProvider.baseUrl : customForm.base_url.trim();
    const model = selectedProvider ? selectedModel : customForm.model.trim();
    const key = selectedProvider ? apiKeyInput : customForm.api_key || "";
    const tags = selectedProvider ? [...selectedProvider.tags] : customForm.tags;

    if (!id) { setFormError("Worker ID is required."); return; }
    if (!baseUrl) { setFormError("Base URL is required."); return; }
    if (!model) { setFormError("Please select or enter a model."); return; }
    if (full) { setFormError(`Pool is full (${CAPACITY}/${CAPACITY}).`); return; }
    if (reservedIds.includes(id) || isReservedWorker({ id } as Worker, reservedIds)) {
      setFormError(`"${id}" is reserved for the orchestration engine.`);
      return;
    }

    setAdding(true);
    try {
      await addWorker({
        id, provider: selectedProvider?.name || "custom",
        base_url: baseUrl, model, tags,
        api_key: key || "",
      });
      // Reset form
      setSelectedProvider(null);
      setApiKeyInput("");
      setFetchedModels(null);
      setSelectedModel("");
      setWorkerId("");
      setShowCustom(false);
      setCustomForm({ id: "", provider: "custom", base_url: "", model: "", tags: [], api_key: "" });
      await refresh();
    } catch (e) {
      setFormError(e instanceof Error ? e.message : String(e));
    } finally {
      setAdding(false);
    }
  }

  async function onRemove(id: string) {
    const snapshot = pool;
    setPool((p) =>
      p ? { ...p, workers: p.workers.filter((w) => w.id !== id), size: Math.max(0, p.size - 1) } : p,
    );
    setHealth((h) => { const n = { ...h }; delete n[id]; return n; });
    try {
      await removeWorker(id);
    } catch (e) {
      setPool(snapshot);
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  async function onTest(id: string) {
    setHealth((h) => ({ ...h, [id]: "loading" }));
    try {
      const result = await getHealth(id);
      setHealth((h) => ({ ...h, [id]: result }));
    } catch (e) {
      setHealth((h) => ({
        ...h,
        [id]: { id, reachable: false, status_code: null, api_key_configured: false, url: "", error: e instanceof Error ? e.message : String(e) },
      }));
    }
  }

  return (
    <section className="fade-up space-y-6">
      <PageHeader
        title="Providers"
        description={
          "Connect up to five LLM providers — local or cloud. Secrets stay on this machine."
        }
        action={
          <span className="chip">
            {size}/{CAPACITY} connected
            {pool?.source === "vault" ? " · vault" : ""}
          </span>
        }
      />


      {error && <ErrorState message={error} />}

      {/* Local one-click: Ollama, LM Studio, MLX */}
      <div className="space-y-3">
        <h2 className="section-label">Local one-click</h2>
        <p className="text-xs text-[var(--muted)] -mt-1">
          Set host/port (and API key if required — oMLX needs one). After connect, models stay
          listed so you can add several without resetting. Sections collapse via the chevron.
        </p>
        {(["ollama", "lmstudio", "mlx"] as LocalKind[]).map((kind) => {
          const panel = localPanels[kind];
          const meta = LOCAL_META[kind];
          const models = panel.discover?.models ?? [];
          const inPoolModels = new Set(
            visibleWorkers
              .filter((w) => (w.provider || "").toLowerCase().includes(kind === "mlx" ? "mlx" : kind))
              .map((w) => w.model),
          );
          for (const m of panel.addedModels) inPoolModels.add(m);

          return (
            <div key={kind} className="card-soft p-0 overflow-hidden">
              <button
                type="button"
                onClick={() => toggleLocalCollapse(kind)}
                className="flex w-full items-center justify-between gap-3 px-5 py-4 text-left hover:bg-[var(--background)]/40"
                aria-expanded={!panel.collapsed}
              >
                <div className="flex min-w-0 items-center gap-3">
                  <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-[var(--background)] border border-[var(--border)]">
                    <svg width="20" height="20" viewBox="0 0 24 24" aria-hidden="true">
                      <circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" strokeWidth="1.5" />
                      <circle cx="12" cy="12" r="3" fill="currentColor" className="text-[var(--accent)]" />
                    </svg>
                  </div>
                  <div className="min-w-0">
                    <h2 className="text-sm font-semibold">{meta.title}</h2>
                    <p className="truncate text-xs text-[var(--muted)]">
                      {panel.discover?.running
                        ? `${models.length} model(s) · ${panel.hostInput}`
                        : meta.blurb}
                    </p>
                  </div>
                </div>
                <span
                  className="shrink-0 text-[var(--muted)] transition-transform"
                  style={{ transform: panel.collapsed ? "rotate(-90deg)" : "rotate(0deg)" }}
                  aria-hidden
                >
                  ▾
                </span>
              </button>

              {!panel.collapsed && (
                <div className="space-y-3 border-t border-[var(--border)] px-5 pb-5 pt-4">
                  <label className="block text-xs font-medium text-[var(--muted)]">
                    Host / port
                    <input
                      type="text"
                      value={panel.hostInput}
                      onChange={(e) => setLocalHost(kind, e.target.value)}
                      placeholder={meta.defaultHost}
                      disabled={panel.loading || panel.connecting}
                      className="field mt-1 font-mono text-xs"
                      autoComplete="off"
                      spellCheck={false}
                    />
                  </label>
                  <label className="block text-xs font-medium text-[var(--muted)]">
                    API key{" "}
                    <span className="font-normal text-[var(--muted-soft)]">
                      {kind === "mlx" ? "(required for oMLX)" : "(optional)"}
                    </span>
                    <input
                      type="password"
                      value={panel.apiKeyInput}
                      onChange={(e) =>
                        patchLocal(kind, {
                          apiKeyInput: e.target.value,
                          error: null,
                          success: null,
                        })
                      }
                      placeholder={
                        kind === "mlx"
                          ? "oMLX API key — required to list & call models"
                          : "Only if your local server requires auth"
                      }
                      disabled={panel.loading || panel.connecting}
                      className="field mt-1 font-mono text-xs"
                      autoComplete="off"
                    />
                  </label>

                  <div className="flex flex-wrap items-center gap-2">
                    <button
                      onClick={() => onConnectLocal(kind)}
                      disabled={panel.loading || full || !panel.hostInput.trim()}
                      className="btn btn-primary"
                    >
                      {panel.loading
                        ? "Connecting…"
                        : panel.discover?.running
                          ? "Refresh models"
                          : meta.button}
                    </button>
                    {panel.discover?.running && (
                      <span className="text-xs text-[var(--good)]">
                        Connected — pick models below (list stays open)
                      </span>
                    )}
                  </div>

                  {panel.discover?.running && (
                    <div className="border-t border-[var(--border)] pt-3">
                      <p className="text-xs text-[var(--muted)]">
                        <span className="font-mono text-[var(--foreground)]">
                          {panel.discover.openai_base_url ||
                            panel.discover.base_url ||
                            panel.hostInput}
                        </span>
                        {models.length === 0
                          ? " — no models listed"
                          : ` — ${models.length} model(s)`}
                      </p>
                      <div className="mt-2.5 flex flex-wrap gap-2">
                        {models
                          .filter(
                            (m) =>
                              !reservedIds.includes(m) &&
                              !reservedIds.includes(
                                `${kind}_${m.replace(/[^a-z0-9_]/gi, "_")}`,
                              ),
                          )
                          .map((m) => {
                            const already = inPoolModels.has(m);
                            return (
                              <button
                                key={m}
                                onClick={() => onPickLocal(kind, m)}
                                disabled={panel.connecting || full || already}
                                title={already ? "Already in pool" : `Add ${m}`}
                                className={
                                  already
                                    ? "btn btn-secondary !px-3 !py-1.5 !text-xs opacity-70"
                                    : "btn btn-secondary !px-3 !py-1.5 !text-xs"
                                }
                              >
                                {already ? `✓ ${m}` : m}
                              </button>
                            );
                          })}
                      </div>
                    </div>
                  )}

                  {panel.error && (
                    <p className="rounded-[var(--radius-sm)] border border-[var(--bad-border)] bg-[var(--bad-bg)] p-3 text-sm text-[var(--bad)]">
                      {panel.error}
                    </p>
                  )}
                  {panel.success && !panel.error && (
                    <p className="rounded-[var(--radius-sm)] border border-[var(--good-border,var(--border))] bg-[var(--good-bg,transparent)] p-3 text-sm text-[var(--good)]">
                      {panel.success}
                    </p>
                  )}
                  {panel.warning && !panel.error && (
                    <p className="rounded-[var(--radius-sm)] border border-[var(--warn-border,var(--border))] bg-[var(--warn-bg,transparent)] p-3 text-sm text-[var(--warn)]">
                      Warm-start: {panel.warning}
                    </p>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* ── Provider selector ── */}
      <div className="card p-0 overflow-hidden">
        <button
          type="button"
          onClick={() => toggleSection("cloud")}
          className="flex w-full items-center justify-between gap-3 px-5 py-4 text-left hover:bg-[var(--background)]/40"
          aria-expanded={!sectionCollapse.cloud}
        >
          <div>
            <h2 className="text-sm font-semibold">Connect a cloud / custom provider</h2>
            <p className="mt-0.5 text-xs text-[var(--muted)]">
              Pick a provider, paste your API key, and select a model.
            </p>
          </div>
          <span
            className="shrink-0 text-[var(--muted)] transition-transform"
            style={{ transform: sectionCollapse.cloud ? "rotate(-90deg)" : "rotate(0deg)" }}
          >
            ▾
          </span>
        </button>
        {!sectionCollapse.cloud && (
        <div className="border-t border-[var(--border)] px-5 pb-5 pt-4">

        <div className="mt-4 space-y-4">
          {/* Step 1: Pick provider */}
          <div>
            <label className="text-xs font-medium text-[var(--muted)]">1. Select provider</label>
            <select
              value={selectedProvider?.id ?? ""}
              onChange={(e) => {
                const id = e.target.value;
                if (!id) { setSelectedProvider(null); return; }
                const prov = SORTED.find((p) => p.id === id) ?? null;
                setSelectedProvider(prov);
              }}
              className="field mt-1"
            >
              <option value="">Choose a provider…</option>
              {SORTED.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.tags.includes("free") ? "🆓 " : p.tags.includes("local") ? "🖥️ " : "☁️ "}
                  {p.name}
                </option>
              ))}
            </select>
          </div>

          {selectedProvider && (
            <>
              {/* Step 2: API Key */}
              {selectedProvider.requiresKey && (
                <div>
                  <label className="text-xs font-medium text-[var(--muted)]">
                    2. Paste your API key
                  </label>
                  <div className="mt-1 flex items-center gap-2">
                    <input
                      type="password"
                      value={apiKeyInput}
                      onChange={(e) => setApiKeyInput(e.target.value)}
                      placeholder={selectedProvider.keyHint}
                      className="field flex-1"
                    />
                    <a
                      href={selectedProvider.docsUrl}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="shrink-0 text-xs text-[var(--accent)] hover:underline"
                    >
                      Get key
                    </a>
                  </div>
                </div>
              )}

              {/* Step 3: Model selection — auto-fetched like Hermes picker */}
              <div>
                <label className="text-xs font-medium text-[var(--muted)]">
                  3. Select model
                </label>
                <div className="mt-1 flex items-center gap-2">
                  {fetchingModels ? (
                    <div className="flex flex-1 items-center gap-2">
                      <div className="h-4 w-4 animate-spin rounded-full border-2 border-[var(--border)] border-t-[var(--accent)]" />
                      <span className="text-xs text-[var(--muted)]">Loading models…</span>
                    </div>
                  ) : fetchedModels !== null && fetchedModels.length > 0 ? (
                    <>
                      <select
                        value={selectedModel}
                        onChange={(e) => setSelectedModel(e.target.value)}
                        className="field flex-1"
                      >
                        <option value="">Select a model…</option>
                        {fetchedModels.map((m) => (
                          <option key={m} value={m}>{m}</option>
                        ))}
                      </select>
                      {fetchedModels.length > 0 && (
                        <span className="shrink-0 text-xs text-[var(--muted-soft)]">{fetchedModels.length} models</span>
                      )}
                    </>
                  ) : fetchedModels !== null && fetchedModels.length === 0 ? (
                    <input
                      value={selectedModel}
                      onChange={(e) => setSelectedModel(e.target.value)}
                      placeholder="Enter model name…"
                      className="field flex-1"
                    />
                  ) : (
                    <>
                      {selectedProvider.knownModels.length > 0 ? (
                        <select
                          value={selectedModel}
                          onChange={(e) => setSelectedModel(e.target.value)}
                          className="field flex-1"
                        >
                          <option value="">Select a model…</option>
                          {selectedProvider.knownModels.map((m) => (
                            <option key={m} value={m}>{m}</option>
                          ))}
                        </select>
                      ) : (
                        <input
                          value={selectedModel}
                          onChange={(e) => setSelectedModel(e.target.value)}
                          placeholder="Enter model name…"
                          className="field flex-1"
                        />
                      )}
                    </>
                  )}
                  {/* Subtle refresh link — like Hermes' refresh catalog */}
                  {!fetchingModels && !NO_FETCH_PROVIDERS.has(selectedProvider.id) && (
                    <button
                      onClick={onFetchModels}
                      className="btn btn-ghost !shrink-0 !px-2 !text-xs"
                      title="Refresh model list from provider API"
                    >
                      ↻ Refresh
                    </button>
                  )}
                </div>
                {fetchError && (
                  <p className="mt-1.5 text-xs text-[var(--warn)]">{fetchError}</p>
                )}
              </div>

              {/* Step 4: Worker ID (auto-filled) */}
              <div>
                <label className="text-xs font-medium text-[var(--muted)]">
                  4. Worker ID <span className="font-normal text-[var(--muted-soft)]">(optional — auto-generated)</span>
                </label>
                <input
                  value={workerId}
                  onChange={(e) => setWorkerId(e.target.value)}
                  placeholder={`${selectedProvider.id}-model`}
                  className="field mt-1"
                />
              </div>

              {formError && <p className="text-xs text-[var(--bad)]">{formError}</p>}

              <button
                onClick={onAdd}
                disabled={adding || full || !selectedModel}
                className="btn btn-primary"
              >
                {adding ? "Adding…" : full ? "Pool full" : `Add ${selectedProvider.name}`}
              </button>
            </>
          )}
        </div>

        {/* ── Custom / Manual toggle ── */}
        <div className="mt-6 border-t border-[var(--border)] pt-4">
          <button
            type="button"
            onClick={() => { setShowCustom((v) => !v); setFormError(null); }}
            className="btn btn-ghost !no-underline text-xs"
          >
            {showCustom ? "− Hide custom provider form" : "+ Add custom provider (manual)"}
          </button>

          {showCustom && (
            <div className="mt-4 space-y-3">
              <p className="text-xs text-[var(--muted)]">
                For providers not in the list above. Fill in all fields manually.
              </p>
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <label className="text-xs font-medium text-[var(--muted)]">
                  ID
                  <input
                    value={customForm.id}
                    onChange={(e) => setCustomForm({ ...customForm, id: e.target.value })}
                    placeholder="my-provider"
                    className="field mt-1"
                  />
                </label>
                <label className="text-xs font-medium text-[var(--muted)]">
                  Base URL
                  <input
                    value={customForm.base_url}
                    onChange={(e) => setCustomForm({ ...customForm, base_url: e.target.value })}
                    placeholder="https://api.example.com/v1"
                    className="field mt-1"
                  />
                </label>
                <label className="text-xs font-medium text-[var(--muted)]">
                  Model
                  <input
                    value={customForm.model}
                    onChange={(e) => setCustomForm({ ...customForm, model: e.target.value })}
                    placeholder="model-name"
                    className="field mt-1"
                  />
                </label>
                <label className="text-xs font-medium text-[var(--muted)]">
                  API Key
                  <input
                    type="password"
                    value={customForm.api_key ?? ""}
                    onChange={(e) => setCustomForm({ ...customForm, api_key: e.target.value.trim() })}
                    placeholder="Paste your API key"
                    className="field mt-1"
                  />
                </label>
                <label className="text-xs font-medium text-[var(--muted)]">
                  Tags
                  <input
                    value={customForm.tags.join(", ")}
                    onChange={(e) =>
                      setCustomForm({
                        ...customForm,
                        tags: e.target.value.split(",").map((t) => t.trim()).filter(Boolean),
                      })
                    }
                    placeholder="cloud, code"
                    className="field mt-1"
                  />
                </label>
              </div>

              {formError && <p className="text-xs text-[var(--bad)]">{formError}</p>}

              <button
                onClick={onAdd}
                disabled={adding || full || !customForm.id.trim() || !customForm.base_url.trim() || !customForm.model.trim()}
                className="btn btn-primary"
              >
                {adding ? "Adding…" : full ? "Pool full" : "Add custom provider"}
              </button>
            </div>
          )}
        </div>
        </div>
        )}
      </div>

      {/* List */}
      <div className="card p-0 overflow-hidden">
        <button
          type="button"
          onClick={() => toggleSection("pool")}
          className="flex w-full items-center justify-between gap-3 px-5 py-4 text-left hover:bg-[var(--background)]/40"
          aria-expanded={!sectionCollapse.pool}
        >
          <h2 className="section-label !mb-0">
            Connected pool{" "}
            <span className="font-normal text-[var(--muted)]">
              ({size}/{CAPACITY})
            </span>
          </h2>
          <span
            className="shrink-0 text-[var(--muted)] transition-transform"
            style={{ transform: sectionCollapse.pool ? "rotate(-90deg)" : "rotate(0deg)" }}
          >
            ▾
          </span>
        </button>
        {!sectionCollapse.pool && (
        <div className="border-t border-[var(--border)] px-5 pb-5 pt-4">
        {loading ? (
          <ul className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {[0, 1, 2].map((i) => (
              <li key={i} className="card p-4">
                <Skeleton className="h-4 w-24" />
                <Skeleton className="mt-2 h-3 w-full" />
                <Skeleton className="mt-1 h-3 w-2/3" />
              </li>
            ))}
          </ul>
        ) : size === 0 ? (
          <EmptyState title="No providers connected">
            <span>
              Use local one-click (Ollama / LM Studio / MLX) or connect a cloud provider.
              Then visit{" "}
              <Link href="/orchestration" className="font-medium text-[var(--accent)] underline">
                Orchestration
              </Link>{" "}
              or{" "}
              <Link href="/plan" className="font-medium text-[var(--accent)] underline">
                Plan
              </Link>
              .
            </span>
          </EmptyState>
        ) : (
          <ul className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {visibleWorkers.map((w) => {
              const h = health[w.id];
              const isOrchestrator = pool?.orchestrator_worker_id === w.id;
              const isVerifier = pool?.verifier_worker_id === w.id;
              const isReserved = isReservedWorker(w, pool?.reserved_ids);
              return (
                <li key={w.id} className="card flex flex-col p-4 text-sm">
                  <div className="flex items-center justify-between gap-2">
                    <span className="flex min-w-0 items-center gap-2 font-medium">
                      <StatusDot
                        status={
                          h === "loading"
                            ? "unknown"
                            : h
                              ? h.reachable
                                ? "up"
                                : "down"
                              : "unknown"
                        }
                      />
                      <span className="truncate">{w.id}</span>
                    </span>
                    <span className="shrink-0 text-xs capitalize text-[var(--muted)]">
                      {w.provider}
                    </span>
                  </div>

                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {isOrchestrator && <Badge tone="good">orchestrator</Badge>}
                    {isVerifier && <Badge tone="good">verifier</Badge>}
                    {isReserved && <Badge tone="warn">engine-reserved</Badge>}
                  </div>

                  <div className="mt-2 flex items-center gap-2">
                    <p className="min-w-0 truncate text-xs text-[var(--muted)]">
                      {w.base_url}
                    </p>
                    <CopyButton value={w.base_url} label="copy" />
                  </div>
                  <p className="truncate text-xs text-[var(--muted)]">{w.model}</p>
                  {w.tags && w.tags.length > 0 && (
                    <div className="mt-2 flex flex-wrap gap-1">
                      {w.tags.map((t) => (
                        <span key={t} className="chip">
                          {t}
                        </span>
                      ))}
                    </div>
                  )}
                  {(w.api_key_configured || w.api_key) && (
                    <p className="mt-1 text-xs text-[var(--muted-soft)]">
                      API key configured ✓
                    </p>
                  )}

                  <div className="mt-2 text-xs">
                    {h === "loading" ? (
                      <span className="text-[var(--muted)]">testing…</span>
                    ) : h ? (
                      <span
                        className={
                          h.reachable ? "text-[var(--good)]" : "text-[var(--bad)]"
                        }
                        title={h.error ?? undefined}
                      >
                        {h.reachable
                          ? `reachable${h.status_code ? ` (${h.status_code})` : ""}`
                          : h.error
                            ? h.error
                            : `unreachable${h.status_code ? ` (${h.status_code})` : ""}`}
                      </span>
                    ) : (
                      <span className="text-[var(--muted-soft)]">not tested</span>
                    )}
                  </div>

                  <div className="mt-auto flex gap-2 pt-3">
                    <button
                      onClick={() => onTest(w.id)}
                      className="btn btn-secondary !px-3 !py-1.5 !text-xs"
                    >
                      Test
                    </button>
                    {!isReserved && (
                      <button
                        onClick={() => onRemove(w.id)}
                        className="btn btn-danger !px-3 !py-1.5 !text-xs"
                      >
                        Remove
                      </button>
                    )}
                  </div>
                </li>
              );
            })}
          </ul>
        )}
        </div>
        )}
      </div>
    </section>
  );
}
