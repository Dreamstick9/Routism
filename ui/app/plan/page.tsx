"use client";

import { useRef, useState } from "react";
import {
  runPlan,
  runPlanStream,
  type PlanResponse,
  type PlanTraceStep,
} from "@/lib/api";
import { Badge, PageHeader } from "../_components/status";

function workerShort(workerId: string): string {
  const parts = workerId.split("_");
  return parts.length > 1 ? parts.slice(1).join("_") : workerId;
}

function stepAccent(verified: boolean, repaired: boolean): string {
  if (repaired) return "border-l-[var(--warn)]";
  if (verified) return "border-l-[var(--good)]";
  return "border-l-[var(--border-strong)]";
}

const EXAMPLE = "Design a REST API for a todo app, then write pytest tests for it.";

type LiveResult = {
  mode?: "trivial" | "complex";
  degraded?: boolean;
  steps: PlanTraceStep[];
  answer?: string;
  inTokens?: number;
  outTokens?: number;
  budgetHit?: boolean;
  error?: string;
};

export default function PlanPage() {
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<PlanResponse | null>(null);
  const [live, setLive] = useState<LiveResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [stream, setStream] = useState(true);
  const abortRef = useRef<AbortController | null>(null);

  async function onRunBlocking(q?: string) {
    const text = (q ?? query).trim();
    if (!text) return;
    setQuery(text);
    setLoading(true);
    setError(null);
    setResult(null);
    setLive(null);
    try {
      const data = await runPlan(text, "conductor");
      if ("error" in data) {
        setError(data.error);
      } else {
        setResult(data);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  async function onRunStream(q?: string) {
    const text = (q ?? query).trim();
    if (!text) return;
    setQuery(text);
    setLoading(true);
    setError(null);
    setResult(null);
    setLive(null);

    const next: LiveResult = { steps: [], inTokens: 0, outTokens: 0 };
    setLive(next);

    const ctrl = new AbortController();
    abortRef.current = ctrl;

    try {
      await runPlanStream(
        text,
        {
          onMeta: (m) => {
            setLive((prev) =>
              prev ? { ...prev, mode: m.mode, degraded: m.degraded } : prev,
            );
          },
          onStep: (s) => {
            setLive((prev) =>
              prev ? { ...prev, steps: [...prev.steps, s] } : prev,
            );
          },
          onDone: (d) => {
            setLive((prev) =>
              prev
                ? {
                    ...prev,
                    answer: d.answer,
                    inTokens: d.usage.orchestration_input_tokens,
                    outTokens: d.usage.orchestration_output_tokens,
                    budgetHit: d.budget_hit,
                    degraded: d.degraded,
                  }
                : prev,
            );
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

  function onRun(q?: string) {
    if (stream) void onRunStream(q);
    else void onRunBlocking(q);
  }

  function onCancel() {
    abortRef.current?.abort();
  }

  const showLive = stream && live;
  const cards: PlanTraceStep[] = showLive ? live!.steps : (result?.steps ?? []);
  const runMode = showLive ? live!.mode : result?.mode;
  const degraded = showLive ? live!.degraded : result?.degraded;
  const answer = showLive ? live!.answer : result?.answer;
  const inTokens = showLive ? live!.inTokens : result?.orchestration_input_tokens;
  const outTokens = showLive ? live!.outTokens : result?.orchestration_output_tokens;
  const budgetHit = showLive ? !!live!.budgetHit : result?.budget_hit;

  return (
    <section className="fade-up space-y-6">
      <PageHeader
        title="Plan"
        description="See how Conductor decomposes a question across your providers. Live streaming shows each step card as it completes."
        action={
          <div className="flex items-center gap-3">
            <Badge tone="good">conductor</Badge>
            <label className="flex cursor-pointer items-center gap-2 text-xs text-[var(--muted)]">
              <input
                type="checkbox"
                checked={stream}
                onChange={(e) => setStream(e.target.checked)}
                disabled={loading}
                className="accent-[var(--accent)]"
              />
              live streaming
            </label>
          </div>
        }
      />

      <div className="card-soft p-5">
        <textarea
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Ask Routism…"
          rows={4}
          className="field textarea"
        />
        <div className="mt-3 flex flex-wrap items-center gap-2.5">
          <button
            onClick={() => onRun()}
            disabled={loading || !query.trim()}
            className="btn btn-primary"
          >
            {loading ? "Running…" : "Run plan"}
          </button>
          {stream && loading && (
            <button onClick={onCancel} className="btn btn-secondary">
              Cancel
            </button>
          )}
          {!result && !live && !error && (
            <button onClick={() => onRun(EXAMPLE)} className="btn btn-ghost">
              try an example
            </button>
          )}
        </div>
      </div>

      {error && (
        <p className="rounded-[var(--radius-sm)] border border-[var(--bad-border)] bg-[var(--bad-bg)] p-3 text-sm text-[var(--bad)]">
          {error}
        </p>
      )}

      {!cards.length && !error && !loading && (
        <div className="rounded-[var(--radius)] border border-dashed border-[var(--border)] px-6 py-10 text-center text-sm text-[var(--muted)]">
          No plan run yet.
        </div>
      )}

      {cards.length > 0 && (
        <div className="space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            {runMode && <span className="chip">mode: {runMode}</span>}
            <span className="chip">steps: {cards.length}</span>
            {inTokens != null && outTokens != null && (
              <span className="chip">
                in: {inTokens} · out: {outTokens}
              </span>
            )}
            {degraded && (
              <Badge tone="warn">conductor fell back to direct step</Badge>
            )}
            {budgetHit && <Badge tone="warn">budget hit</Badge>}
            {loading && <span className="chip animate-pulse">streaming…</span>}
          </div>

          {cards.map((s) => (
            <div
              key={s.index}
              className={`card border-l-4 p-4 text-sm ${stepAccent(s.verified, s.repaired)}`}
            >
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="font-medium">Step {s.index + 1}</span>
                <span className="flex flex-wrap items-center gap-1.5 text-xs text-[var(--muted)]">
                  {s.worker_id}
                  <span className="text-[var(--muted-soft)]">
                    ({workerShort(s.worker_id)})
                  </span>
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

          {answer && (
            <div className="card-soft border-2 border-[var(--accent)]/30 p-5 text-sm">
              <span className="section-label text-[var(--accent)]">Final answer</span>
              <p className="mt-2 whitespace-pre-wrap leading-relaxed">{answer}</p>
            </div>
          )}
        </div>
      )}
    </section>
  );
}
