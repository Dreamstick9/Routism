"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  runPlanStream,
  type PlanTraceStep,
  type ParallelCandidate,
  type PairwiseCheck,
  type SynthesisTrace,
  type ConductorSubtask,
  type ConductorPlanEvent,
  type DagLayerCompleteEvent,
  type KSamplePickEvent,
  type ReplanEvent,
} from "@/lib/api";
import { Badge, PageHeader } from "../_components/status";

// Orchestration is Conductor-only (team DAG). Parallel vote mode removed.

const EXAMPLE =
  "Explain quantum entanglement to a 10-year-old, then compare it to classical correlation.";

function colourForScore(score: number): string {
  if (score >= 8) return "text-[var(--good)]";
  if (score >= 5) return "text-[var(--warn)]";
  return "text-[var(--bad)]";
}

function scoreBg(score: number): string {
  if (score >= 8) return "bg-[var(--good-bg)] border-[var(--good-border)]";
  if (score >= 5) return "bg-[var(--warn-bg)] border-[var(--warn-border)]";
  return "bg-[var(--bad-bg)] border-[var(--bad-border)]";
}

function workerShort(workerId: string): string {
  // Strip sample suffix: worker/subtask/s0 → worker
  const base = workerId.split("/")[0] ?? workerId;
  const parts = base.split("_");
  return parts.length > 1 ? parts.slice(1).join("_") : base;
}

function baseWorkerId(workerId: string): string {
  return workerId.split("/")[0] ?? workerId;
}

type LayerLive = {
  layer: number;
  subtaskIds: string[];
  status: "running" | "complete";
  elapsedMs?: number;
  subtaskCount?: number;
  meanScore?: number;
};

type LiveResult = {
  mode?: "trivial" | "complex" | "conductor";
  degraded?: boolean;
  degradedReason?: string;
  missingEngineModels?: string[];
  partialSuccess?: boolean;
  parallel?: boolean;
  orchestration?: string;
  dagLayers?: number;
  dagSubtasks?: number;
  pool?: string[];
  steps: PlanTraceStep[];
  candidates: ParallelCandidate[];
  pairwise?: PairwiseCheck[];
  synthesis?: SynthesisTrace;
  answer?: string;
  inTokens?: number;
  outTokens?: number;
  budgetHit?: boolean;
  error?: string;
  // PR-5 Conductor
  conductorSubtasks?: ConductorSubtask[];
  conductorLayers?: string[][];
  layerTimeline?: LayerLive[];
  kSamplePicks?: KSamplePickEvent[];
  fanOutWorkers?: string[];
  // PR-7 bounded replan
  replanEvents?: ReplanEvent[];
};

function computeRoster(live: LiveResult): {
  pool: string[];
  used: string[];
  idle: string[];
  assigned: string[];
  failed: string[];
  /** Workers assigned but not yet succeeded/failed (in-flight). */
  pending: string[];
} {
  // Union every signal so we never drop a connected worker — including ones
  // the plan assigned (e.g. opencode) that a partial meta/fan_out missed.
  const poolSet = new Set<string>();
  for (const w of live.pool ?? []) poolSet.add(baseWorkerId(w));
  for (const w of live.fanOutWorkers ?? []) poolSet.add(baseWorkerId(w));

  const assigned = new Set<string>();
  for (const st of live.conductorSubtasks ?? []) {
    for (const w of st.assigned_workers ?? []) {
      const id = baseWorkerId(w);
      assigned.add(id);
      poolSet.add(id);
    }
    if (st.assigned_worker) {
      const id = baseWorkerId(st.assigned_worker);
      assigned.add(id);
      poolSet.add(id);
    }
    if (st.selected_worker_id) {
      const id = baseWorkerId(st.selected_worker_id);
      assigned.add(id);
      poolSet.add(id);
    }
    // Samples also prove participation even when selected_worker_id is late
    for (const s of st.samples ?? []) {
      if (s.worker_id) {
        const id = baseWorkerId(s.worker_id);
        assigned.add(id);
        poolSet.add(id);
      }
    }
  }

  const used = new Set<string>();
  const failed = new Set<string>();
  for (const c of live.candidates) {
    const id = baseWorkerId(c.worker_id);
    poolSet.add(id);
    if (c.error) failed.add(id);
    else if (c.answer) used.add(id);
  }
  for (const st of live.conductorSubtasks ?? []) {
    if (st.selected_worker_id && st.result && !st.error) {
      used.add(baseWorkerId(st.selected_worker_id));
    } else if (st.assigned_worker && st.result && !st.error) {
      used.add(baseWorkerId(st.assigned_worker));
    } else if (st.assigned_worker && st.error) {
      const id = baseWorkerId(st.assigned_worker);
      failed.add(id);
      poolSet.add(id);
    }
    for (const s of st.samples ?? []) {
      if (!s.worker_id) continue;
      const id = baseWorkerId(s.worker_id);
      if (s.error) failed.add(id);
      else if (s.answer) used.add(id);
    }
  }
  for (const k of live.kSamplePicks ?? []) {
    if (k.winner) {
      const id = baseWorkerId(k.winner);
      used.add(id);
      poolSet.add(id);
    }
    for (const L of k.losers ?? []) poolSet.add(baseWorkerId(L));
  }

  // Prefer meta/live.pool order so connected count is stable; append any extras.
  const ordered: string[] = [];
  for (const w of live.pool ?? []) {
    const id = baseWorkerId(w);
    if (poolSet.has(id) && !ordered.includes(id)) ordered.push(id);
  }
  for (const w of live.fanOutWorkers ?? []) {
    const id = baseWorkerId(w);
    if (poolSet.has(id) && !ordered.includes(id)) ordered.push(id);
  }
  for (const w of poolSet) {
    if (!ordered.includes(w)) ordered.push(w);
  }

  // Idle = in pool but never assigned this run (not "still running").
  const idle = ordered.filter((w) => !assigned.has(w));
  // Pending = assigned, not yet succeeded or failed
  const pending = ordered.filter(
    (w) => assigned.has(w) && !used.has(w) && !failed.has(w),
  );
  return {
    pool: ordered,
    used: [...used],
    idle,
    assigned: [...assigned],
    failed: [...failed],
    pending,
  };
}

export default function OrchestrationPage() {
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [live, setLive] = useState<LiveResult | null>(null);
  const [error, setError] = useState<string | null>(null);
    const abortRef = useRef<AbortController | null>(null);

  async function onRun(q?: string) {
    const text = (q ?? query).trim();
    if (!text) return;
    setQuery(text);
    setLoading(true);
    setError(null);
    setLive(null);

    const next: LiveResult = {
      steps: [],
      candidates: [],
      inTokens: 0,
      outTokens: 0,
      layerTimeline: [],
      kSamplePicks: [],
      replanEvents: [],
    };
    setLive(next);

    const ctrl = new AbortController();
    abortRef.current = ctrl;

    try {
      await runPlanStream(
        text,
        {
          onMeta: (m) => {
            setLive((prev) =>
              prev
                ? {
                    ...prev,
                    mode: m.mode,
                    degraded: m.degraded,
                    degradedReason: m.degraded_reason ?? prev.degradedReason,
                    missingEngineModels:
                      m.missing_engine_models ?? prev.missingEngineModels,
                    parallel:
                      m.parallel === true ||
                      m.mode === "complex" ||
                      m.orchestration === "conductor" ||
                      m.orchestration === "conductor_degraded" ||
                      prev.parallel,
                    orchestration: m.orchestration ?? prev.orchestration,
                    dagLayers: m.dag_layers ?? prev.dagLayers,
                    dagSubtasks: m.dag_subtasks ?? prev.dagSubtasks,
                    pool: m.pool ?? prev.pool,
                  }
                : prev,
            );
          },
          onConductorPlan: (p: ConductorPlanEvent) => {
            setLive((prev) => {
              if (!prev) return prev;
              const subtasks = p.plan?.subtasks ?? [];
              const layers = p.plan?.layers ?? [];
              // Merge full pool + every assignee so roster never shows N-1 when
              // e.g. opencode is assigned but meta was incomplete.
              const fromAssign: string[] = [];
              for (const st of subtasks) {
                if (st.assigned_worker) fromAssign.push(st.assigned_worker);
                for (const w of st.assigned_workers ?? []) fromAssign.push(w);
              }
              const pool = [
                ...new Set([
                  ...(prev.pool ?? []),
                  ...(p.pool ?? []),
                  ...fromAssign,
                ]),
              ];
              return {
                ...prev,
                parallel: true,
                orchestration: prev.orchestration ?? "conductor",
                conductorSubtasks: subtasks,
                conductorLayers: layers,
                dagLayers: p.layers ?? layers.length ?? prev.dagLayers,
                dagSubtasks: p.subtasks ?? subtasks.length ?? prev.dagSubtasks,
                pool,
              };
            });
          },
          onDagLayerStart: (e) => {
            setLive((prev) => {
              if (!prev) return prev;
              const timeline = [...(prev.layerTimeline ?? [])];
              const existing = timeline.findIndex((t) => t.layer === e.layer);
              const entry: LayerLive = {
                layer: e.layer,
                subtaskIds: e.subtask_ids ?? [],
                status: "running",
              };
              if (existing >= 0) timeline[existing] = entry;
              else timeline.push(entry);
              timeline.sort((a, b) => a.layer - b.layer);
              return { ...prev, layerTimeline: timeline };
            });
          },
          onDagLayerComplete: (e: DagLayerCompleteEvent) => {
            setLive((prev) => {
              if (!prev) return prev;
              const timeline = [...(prev.layerTimeline ?? [])];
              const existing = timeline.findIndex((t) => t.layer === e.layer);
              const entry: LayerLive = {
                layer: e.layer,
                subtaskIds:
                  existing >= 0 ? timeline[existing].subtaskIds : [],
                status: "complete",
                elapsedMs: e.elapsed_ms,
                subtaskCount: e.subtask_count,
                meanScore: e.mean_score,
              };
              if (existing >= 0) timeline[existing] = entry;
              else timeline.push(entry);
              timeline.sort((a, b) => a.layer - b.layer);
              return { ...prev, layerTimeline: timeline };
            });
          },
          onKSamplePick: (e: KSamplePickEvent) => {
            setLive((prev) =>
              prev
                ? {
                    ...prev,
                    kSamplePicks: [...(prev.kSamplePicks ?? []), e],
                  }
                : prev,
            );
          },
          onReplan: (e: ReplanEvent) => {
            setLive((prev) =>
              prev
                ? {
                    ...prev,
                    replanEvents: [...(prev.replanEvents ?? []), e],
                    // Refresh plan board assignments after replan
                    conductorSubtasks: prev.conductorSubtasks
                      ? prev.conductorSubtasks.map((st) =>
                          e.new_subtask_ids?.includes(st.id)
                            ? {
                                ...st,
                                result: null,
                                error: null,
                                samples: [],
                                selected_worker_id: null,
                              }
                            : st,
                        )
                      : prev.conductorSubtasks,
                  }
                : prev,
            );
          },
          onStep: (s) => {
            setLive((prev) =>
              prev ? { ...prev, steps: [...prev.steps, s] } : prev,
            );
          },
          onFanOut: (f) => {
            setLive((prev) => {
              if (!prev) return prev;
              const merged = [
                ...new Set([
                  ...(prev.pool ?? []),
                  ...(f.workers ?? []),
                ]),
              ];
              return {
                ...prev,
                parallel: true,
                fanOutWorkers: f.workers ?? prev.fanOutWorkers,
                pool: merged,
              };
            });
          },
          onCandidate: (c) => {
            setLive((prev) =>
              prev ? { ...prev, candidates: [...prev.candidates, c] } : prev,
            );
          },
          onScore: (scores) => {
            setLive((prev) => {
              if (!prev) return prev;
              const scoreMap = new Map(scores.map((s) => [s.worker_id, s]));
              return {
                ...prev,
                candidates: prev.candidates.map((c) => {
                  const s = scoreMap.get(c.worker_id);
                  return s
                    ? { ...c, score: s.score, score_reason: s.reason }
                    : c;
                }),
              };
            });
          },
          onSynthesis: (s) => {
            setLive((prev) => (prev ? { ...prev, synthesis: s } : prev));
          },
          onDone: (d) => {
            setLive((prev) => {
              if (!prev) return prev;
              const cond = d.parallel?.conductor as
                | {
                    layers?: string[][];
                    subtasks?: ConductorSubtask[];
                    models_used?: string[];
                  }
                | undefined;
              const extra = cond?.models_used ?? [];
              const subtasks = cond?.subtasks ?? prev.conductorSubtasks;
              const fromAssign: string[] = [];
              for (const st of subtasks ?? []) {
                if (st.assigned_worker) fromAssign.push(st.assigned_worker);
                for (const w of st.assigned_workers ?? []) fromAssign.push(w);
              }
              const pool = [
                ...new Set([
                  ...(prev.pool ?? []),
                  ...extra,
                  ...fromAssign,
                ]),
              ];
              return {
                ...prev,
                answer: d.answer,
                inTokens: d.usage.orchestration_input_tokens,
                outTokens: d.usage.orchestration_output_tokens,
                budgetHit: d.budget_hit,
                degraded: d.degraded,
                degradedReason: d.degraded_reason ?? prev.degradedReason,
                missingEngineModels:
                  d.missing_engine_models ?? prev.missingEngineModels,
                partialSuccess: d.partial_success ?? prev.partialSuccess,
                candidates: d.parallel?.fan_out ?? prev.candidates,
                pairwise: d.parallel?.pairwise ?? prev.pairwise,
                synthesis: d.parallel?.synthesis ?? prev.synthesis,
                parallel: d.parallel ? true : prev.parallel,
                conductorSubtasks: subtasks,
                conductorLayers: cond?.layers ?? prev.conductorLayers,
                pool,
              };
            });
          },
          onError: (message) => {
            setError(message);
          },
        },
        ctrl.signal,
        "conductor",
      );
    } catch (e) {
      if ((e as Error).name !== "AbortError") {
        setError(e instanceof Error ? e.message : String(e));
      }
    } finally {
      setLoading(false);
      abortRef.current = null;
    }
  }

  function onCancel() {
    abortRef.current?.abort();
  }

  const hasParallel =
    live?.parallel === true && live?.candidates && live.candidates.length > 0;
  const isConductor =
    live?.orchestration === "conductor" ||
    live?.orchestration === "conductor_degraded" ||
    (live?.conductorSubtasks != null && live.conductorSubtasks.length > 0);
  const planning =
    loading && live != null && live.mode == null && !live.orchestration;
  const roster = useMemo(
    () => (live ? computeRoster(live) : null),
    [live],
  );

  return (
    <section className="fade-up space-y-6">
      <PageHeader
        title="Orchestration"
        description="Conductor splits hard work across your models, runs independent steps together, and merges one answer."
        action={
          <div className="flex items-center gap-2">
            {live?.orchestration === "conductor_degraded" ? (
              <Badge tone="warn">conductor degraded</Badge>
            ) : (
              <Badge tone="good">conductor</Badge>
            )}
          </div>
        }
      />

      <div className="card-soft p-5">
        <textarea
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Ask something multi-step — e.g. implement, then explain, then edge cases…"
          rows={4}
          className="field textarea"
        />
        <div className="mt-3 flex flex-wrap items-center gap-2.5">
          <button
            onClick={() => onRun()}
            disabled={loading || !query.trim()}
            className="btn btn-primary"
          >
            {loading
              ? planning
                ? "Planning team…"
                : "Running…"
              : "Run orchestration"}
          </button>
          {loading && (
            <button onClick={onCancel} className="btn btn-secondary">
              Cancel
            </button>
          )}
          {!live && !error && (
            <button onClick={() => onRun(EXAMPLE)} className="btn btn-ghost">
              try an example
            </button>
          )}
        </div>
      </div>

      {error && (
        <div className="rounded-[var(--radius-sm)] border border-[var(--bad-border)] bg-[var(--bad-bg)] p-3 text-sm text-[var(--bad)]">
          <p>{error}</p>
          
        </div>
      )}

      {!live && !error && !loading && (
        <div className="rounded-[var(--radius)] border border-dashed border-[var(--border)] px-6 py-10 text-center text-sm text-[var(--muted)]">
          No run yet — ask a multi-step question to see the team plan and layers.
        </div>
      )}

      {live && (
        <div className="space-y-5">
          <div className="flex flex-wrap items-center gap-2">
            {planning && (
              <span className="chip animate-pulse">Planning DAG…</span>
            )}
            {live.mode && (
              <span className="chip">
                mode:{" "}
                {isConductor
                  ? live.orchestration === "conductor_degraded"
                    ? "conductor (degraded)"
                    : "conductor"
                  : live.mode}
              </span>
            )}
            {live.dagLayers != null && live.dagLayers > 0 && (
              <span className="chip">
                dag: {live.dagSubtasks ?? "?"} subtasks · {live.dagLayers}{" "}
                layers
              </span>
            )}
            {live.degraded && (
              <Badge tone="warn">
                {live.degradedReason === "engine_unavailable"
                  ? "engine unavailable — multi-worker fallback"
                  : live.degradedReason === "no_workers"
                    ? "no workers connected"
                    : live.orchestration === "conductor_degraded" ||
                        live.orchestration === "conductor"
                      ? "conductor degraded"
                      : "degraded run"}
              </Badge>
            )}
            {live.partialSuccess && (
              <Badge tone="warn">partial success — some steps failed</Badge>
            )}
            {live.replanEvents && live.replanEvents.length > 0 && (
              <Badge tone="warn">
                replan ×{live.replanEvents.length} (score floor)
              </Badge>
            )}
            {live.degraded &&
              live.missingEngineModels &&
              live.missingEngineModels.length > 0 && (
                <span className="chip">
                  missing engine: {live.missingEngineModels.join(", ")}
                </span>
              )}
            {live.degraded && live.degradedReason && (
              <p className="w-full text-xs text-[var(--warn)]">
                {live.degradedReason === "engine_unavailable"
                  ? "Local engine models (Ollama) are missing or unreachable. Work was fanned out to your connected workers without full plan/score/synth."
                  : live.degradedReason === "no_workers"
                    ? "Add at least one worker on the Providers page."
                    : `degraded_reason: ${live.degradedReason}`}
              </p>
            )}
            {live.budgetHit && <Badge tone="warn">budget hit</Badge>}
            {live.inTokens != null && live.outTokens != null && (
              <span className="chip">
                in: {live.inTokens} · out: {live.outTokens}
              </span>
            )}
            {loading && !planning && (
              <span className="chip animate-pulse">streaming…</span>
            )}
          </div>

          {/* PR-7: bounded replan banner */}
          {live.replanEvents && live.replanEvents.length > 0 && (
            <div className="rounded-[var(--radius-sm)] border border-[var(--warn-border)] bg-[var(--warn-bg)] p-3 text-sm text-[var(--warn)]">
              <p className="font-medium">
                Replanning remaining work — layer mean score below floor
              </p>
              <ul className="mt-2 space-y-1 text-xs">
                {live.replanEvents.map((r, i) => (
                  <li key={`${r.layer}-${i}`}>
                    Layer {r.layer}
                    {r.mean_score != null && (
                      <> · mean {r.mean_score.toFixed(1)}</>
                    )}
                    {r.reason ? ` · ${r.reason}` : ""}
                    {r.new_subtask_ids && r.new_subtask_ids.length > 0 && (
                      <> · reassigned: {r.new_subtask_ids.join(", ")}</>
                    )}
                  </li>
                ))}
              </ul>
              <p className="mt-1 text-xs text-[var(--muted)]">
                At most one replan per run. Failed steps are retried with
                different workers when possible.
              </p>
            </div>
          )}

          {/* PR-5: team roster — connected = full pool, not only who ran */}
          {roster && roster.pool.length > 0 && (
            <div className="card p-4 text-sm">
              <h2 className="section-label mb-2">
                Team roster — connected {roster.pool.length} · assigned{" "}
                {roster.assigned.length} · succeeded {roster.used.length}
                {roster.failed.length > 0
                  ? ` · failed ${roster.failed.length}`
                  : ""}
                {roster.idle.length > 0 ? ` · idle ${roster.idle.length}` : ""}
              </h2>
              <ul className="flex flex-wrap gap-2">
                {roster.pool.map((w) => {
                  const did = roster.used.includes(w);
                  const failed = roster.failed.includes(w);
                  const wasAssigned = roster.assigned.includes(w);
                  const pending = roster.pending.includes(w);
                  return (
                    <li
                      key={w}
                      className={`rounded-[var(--radius-pill)] border px-2.5 py-1 text-xs ${
                        did
                          ? "border-[var(--good-border)] bg-[var(--good-bg)] text-[var(--good)]"
                          : failed
                            ? "border-[var(--bad-border)] bg-[var(--bad-bg)] text-[var(--bad)]"
                            : wasAssigned
                              ? "border-[var(--warn-border)] bg-[var(--warn-bg)] text-[var(--warn)]"
                              : "border-[var(--border)] text-[var(--muted)]"
                      }`}
                      title={
                        did
                          ? "succeeded this run"
                          : failed
                            ? "assigned but failed"
                            : pending
                              ? "assigned, in progress"
                              : wasAssigned
                                ? "assigned"
                                : "connected, not assigned this run"
                      }
                    >
                      {did ? "✓ " : failed ? "✗ " : wasAssigned ? "● " : "○ "}
                      {workerShort(w)}
                    </li>
                  );
                })}
              </ul>
              <p className="mt-2 text-xs text-[var(--muted-soft)]">
                Connected = full pool · ✓ succeeded · ● assigned · ✗ failed · ○
                idle (connected, not assigned)
                {roster.idle.length > 0
                  ? ` · Idle: ${roster.idle.map(workerShort).join(", ")}`
                  : ""}
              </p>
            </div>
          )}

          {/* PR-5: Conductor plan board */}
          {isConductor &&
            live.conductorSubtasks &&
            live.conductorSubtasks.length > 0 && (
              <div>
                <h2 className="section-label mb-3">
                  Plan — {live.conductorSubtasks.length} subtasks
                  {live.conductorLayers
                    ? ` · ${live.conductorLayers.length} layers`
                    : ""}
                </h2>
                <ol className="space-y-2">
                  {live.conductorSubtasks.map((st) => (
                    <li key={st.id} className="card p-4 text-sm">
                      <div className="flex flex-wrap items-start justify-between gap-2">
                        <div className="min-w-0">
                          <p className="font-medium">
                            <span className="text-[var(--muted)]">{st.id}</span>
                            {st.critical && (
                              <span className="ml-2">
                                <Badge tone="warn">critical</Badge>
                              </span>
                            )}
                          </p>
                          <p className="mt-1 text-[var(--foreground)]">
                            {st.prompt}
                          </p>
                          {st.tags && st.tags.length > 0 && (
                            <p className="mt-1 text-xs text-[var(--muted)]">
                              tags: {st.tags.join(", ")}
                            </p>
                          )}
                          {st.depends_on && st.depends_on.length > 0 && (
                            <p className="mt-0.5 text-xs text-[var(--muted-soft)]">
                              waits on: {st.depends_on.join(", ")}
                            </p>
                          )}
                        </div>
                        <div className="shrink-0 text-right text-xs">
                          {(st.assigned_workers &&
                            st.assigned_workers.length > 0
                            ? st.assigned_workers
                            : st.assigned_worker
                              ? [st.assigned_worker]
                              : []
                          ).map((w) => (
                            <span key={w} className="chip ml-1">
                              {workerShort(w)}
                            </span>
                          ))}
                          {st.selected_worker_id &&
                            st.selected_worker_id !== st.assigned_worker && (
                              <p className="mt-1 text-[var(--good)]">
                                picked: {workerShort(st.selected_worker_id)}
                              </p>
                            )}
                        </div>
                      </div>
                      {st.assignment_reason && (
                        <p className="mt-2 border-t border-[var(--border)] pt-2 text-xs text-[var(--muted-soft)]">
                          why: {st.assignment_reason}
                        </p>
                      )}
                    </li>
                  ))}
                </ol>
              </div>
            )}

          {/* PR-5: layer timeline */}
          {isConductor &&
            live.layerTimeline &&
            live.layerTimeline.length > 0 && (
              <div>
                <h2 className="section-label mb-3">Layer timeline</h2>
                <ul className="space-y-2">
                  {live.layerTimeline.map((L) => (
                    <li
                      key={L.layer}
                      className={`card flex flex-wrap items-center justify-between gap-2 p-3 text-sm ${
                        L.status === "running"
                          ? "border-[var(--accent)]/40"
                          : ""
                      }`}
                    >
                      <span className="font-medium">
                        Layer {L.layer}
                        {L.status === "running" && (
                          <span className="ml-2 animate-pulse text-xs text-[var(--accent)]">
                            running…
                          </span>
                        )}
                        {L.status === "complete" && (
                          <span className="ml-2 text-xs text-[var(--good)]">
                            complete
                          </span>
                        )}
                      </span>
                      <span className="text-xs text-[var(--muted)]">
                        {L.subtaskIds.join(", ") ||
                          `${L.subtaskCount ?? "?"} subtasks`}
                        {L.elapsedMs != null && ` · ${L.elapsedMs}ms`}
                        {L.meanScore != null &&
                          ` · mean ${L.meanScore.toFixed(1)}`}
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            )}

          {/* PR-5: k-sample picks */}
          {live.kSamplePicks && live.kSamplePicks.length > 0 && (
            <div className="card p-4 text-sm">
              <h2 className="section-label mb-2">Critical picks (k-sample)</h2>
              <ul className="space-y-2 text-xs">
                {live.kSamplePicks.map((k, i) => (
                  <li
                    key={`${k.subtask_id}-${i}`}
                    className="rounded-[var(--radius-sm)] bg-[var(--background)] px-3 py-2"
                  >
                    <span className="font-medium">{k.subtask_id}</span>
                    {k.winner && (
                      <>
                        <span className="mx-1.5 text-[var(--muted-soft)]">
                          kept
                        </span>
                        <span className="text-[var(--good)]">
                          {workerShort(k.winner)}
                        </span>
                      </>
                    )}
                    {k.losers && k.losers.length > 0 && (
                      <span className="ml-1.5 text-[var(--muted)]">
                        over {k.losers.map(workerShort).join(", ")}
                      </span>
                    )}
                    {k.method && (
                      <span className="ml-2 text-[var(--muted-soft)]">
                        ({k.method})
                      </span>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {hasParallel && (
            <>
              <div>
                <h2 className="section-label mb-3">
                  {isConductor
                    ? `Step outputs — ${live.candidates.length}`
                    : `Fan-out — ${live.candidates.length} workers`}
                </h2>
                <ul className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                  {live.candidates.map((c, idx) => (
                    <li
                      key={`${c.worker_id}-${idx}`}
                      className={`card p-4 text-sm ${
                        c.error
                          ? "border-[var(--bad-border)] bg-[var(--bad-bg)]"
                          : ""
                      }`}
                    >
                      <div className="flex items-start justify-between gap-2">
                        <div className="min-w-0">
                          <p className="truncate font-medium">
                            {workerShort(c.worker_id)}
                          </p>
                          {c.role && (
                            <p className="mt-0.5 text-xs text-[var(--muted)]">
                              {c.role}
                              {c.elapsed_ms != null &&
                                ` · ${Math.round(c.elapsed_ms)}ms`}
                            </p>
                          )}
                        </div>
                        {c.score != null && (
                          <span
                            className={`shrink-0 rounded-[var(--radius-pill)] border px-2 py-0.5 text-xs font-semibold ${colourForScore(c.score)} ${scoreBg(c.score)}`}
                          >
                            {c.score}/10
                          </span>
                        )}
                      </div>
                      {c.error ? (
                        <p className="mt-2 text-xs text-[var(--bad)]">
                          {c.error}
                        </p>
                      ) : (
                        <p className="scroll-soft mt-3 max-h-40 overflow-y-auto whitespace-pre-wrap text-xs leading-relaxed text-[var(--muted)]">
                          {c.answer}
                        </p>
                      )}
                      {c.score_reason && (
                        <p className="mt-2 border-t border-[var(--border)] pt-2 text-xs text-[var(--muted-soft)]">
                          judge: {c.score_reason}
                        </p>
                      )}
                    </li>
                  ))}
                </ul>
              </div>

              {live.pairwise && live.pairwise.length > 0 && (
                <div className="card p-4 text-sm">
                  <h3 className="section-label text-[var(--muted)]">
                    Pairwise cross-check
                  </h3>
                  <ul className="mt-2 space-y-2 text-xs">
                    {live.pairwise.map((p, i) => (
                      <li
                        key={i}
                        className="rounded-[var(--radius-sm)] bg-[var(--background)] px-3 py-2"
                      >
                        <span className="font-medium text-[var(--good)]">
                          {p.winner}
                        </span>
                        <span className="mx-1.5 text-[var(--muted-soft)]">
                          over
                        </span>
                        <span className="text-[var(--bad)]">{p.loser}</span>
                        {p.reason && (
                          <p className="mt-1 text-[var(--muted)]">{p.reason}</p>
                        )}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </>
          )}

          {hasParallel && live.synthesis && (
            <div className="card-soft border-[var(--accent)]/25 p-4 text-sm">
              <h2 className="section-label">
                Synthesis
                <span className="ml-2 font-normal text-[var(--muted)]">
                  ({live.synthesis.engine}) ·{" "}
                  {live.synthesis.contributors.map(workerShort).join(", ")}
                </span>
              </h2>
              {live.synthesis.strategy && (
                <p className="mt-1 text-xs text-[var(--muted)]">
                  strategy: {live.synthesis.strategy}
                </p>
              )}
              <p className="mt-3 whitespace-pre-wrap text-xs leading-relaxed text-[var(--muted)]">
                {live.synthesis.draft}
              </p>
            </div>
          )}

          {!hasParallel && live.steps.length > 0 && (
            <div className="space-y-3">
              <h2 className="section-label">Steps — {live.steps.length}</h2>
              {live.steps.map((s) => (
                <div
                  key={s.index}
                  className={`card border-l-4 p-4 text-sm ${
                    s.verified
                      ? "border-l-[var(--good)]"
                      : s.repaired
                        ? "border-l-[var(--warn)]"
                        : "border-l-[var(--border-strong)]"
                  }`}
                >
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="font-medium">Step {s.index + 1}</span>
                    <span className="flex flex-wrap items-center gap-1.5 text-xs text-[var(--muted)]">
                      {s.worker_id}
                      {s.verified && <Badge tone="good">verified</Badge>}
                      {s.repaired && <Badge tone="warn">repaired</Badge>}
                    </span>
                  </div>
                  <p className="mt-1.5 text-[var(--foreground)]">{s.subtask}</p>
                  <p className="mt-2 whitespace-pre-wrap text-xs leading-relaxed text-[var(--muted)]">
                    {s.output}
                  </p>
                </div>
              ))}
            </div>
          )}

          {live.answer && (
            <div className="card-soft border-2 border-[var(--accent)]/30 p-5 text-sm">
              <span className="section-label text-[var(--accent)]">
                Final answer
                {roster && roster.pool.length > 0
                  ? ` · team ${roster.used.length}/${roster.pool.length}`
                  : ""}
              </span>
              <p className="mt-2 whitespace-pre-wrap leading-relaxed text-[var(--foreground)]">
                {live.answer}
              </p>
            </div>
          )}
        </div>
      )}
    </section>
  );
}
