"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { getMetrics, type MetricsResponse } from "@/lib/api";
import {
  Skeleton,
  EmptyState,
  ErrorState,
  StatusDot,
  PageHeader,
} from "../_components/status";

export default function MetricsPage() {
  const [metrics, setMetrics] = useState<MetricsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    (async () => {
      setLoading(true);
      setError(null);
      try {
        const m = await getMetrics();
        if (active) setMetrics(m);
      } catch (e) {
        if (active) setError(e instanceof Error ? e.message : String(e));
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => {
      active = false;
    };
  }, []);

  if (loading) {
    return (
      <section className="fade-up space-y-6">
        <PageHeader title="Metrics" description="Loading pool and eval snapshot…" />
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-24" />
          ))}
        </div>
      </section>
    );
  }

  if (error) {
    return (
      <section className="fade-up space-y-6">
        <PageHeader title="Metrics" />
        <ErrorState message={`Could not load metrics: ${error}`} />
      </section>
    );
  }

  const pool = metrics?.pool ?? null;
  const evalData = metrics?.eval ?? null;
  const routism = (evalData?.routism as MetricsRoutismEval) ?? null;
  const zeroRouter = (evalData?.zero_router as MetricsZeroRouterEval) ?? null;
  const overhead = evalData?.overhead_ratio;
  const verdict = evalData?.verdict;
  const records = (evalData?.records as EvalRecord[] | undefined) ?? [];

  return (
    <section className="fade-up space-y-8">
      <PageHeader
        title="Metrics"
        description="Pool capacity and the most recent Phase-2 eval (accuracy, token overhead, win/loss vs Zero-Router)."
        action={
          metrics?.generated_at ? (
            <span className="chip">
              generated {formatTs(metrics.generated_at)}
            </span>
          ) : undefined
        }
      />

      <div>
        <h2 className="section-label mb-3">Pool</h2>
        {!pool ? (
          <EmptyState title="No routism.yaml loaded">
            <span>
              Add a provider to boot the orchestrator — see{" "}
              <Link
                href="/providers"
                className="font-medium text-[var(--accent)] underline"
              >
                Providers
              </Link>
              .
            </span>
          </EmptyState>
        ) : (
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Card label="Pool size" value={`${pool.size}/${pool.capacity}`} />
            <Card
              label="Orchestrator"
              value={pool.orchestrator_worker_id ?? "not set"}
              tone={pool.orchestrator_worker_id ? "neutral" : "warn"}
            />
            <Card
              label="Verifier"
              value={pool.verifier_worker_id ?? "not set"}
              tone={pool.verifier_worker_id ? "neutral" : "warn"}
            />
            <Card label="Workers" value={pool.workers.join(", ") || "—"} />
          </div>
        )}
      </div>

      <div>
        <h2 className="section-label mb-3">Last Phase-2 eval</h2>
        {!evalData ? (
          <EmptyState title="No eval results yet">
            <span>
              Run the Phase-2 harness to populate{" "}
              <code className="rounded bg-[var(--border)] px-1.5 py-0.5 text-xs">
                phase2_results.json
              </code>{" "}
              on the backend.
            </span>
          </EmptyState>
        ) : (
          <>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <Card
                label="Routism accuracy"
                value={
                  routism?.accuracy != null ? formatPct(routism.accuracy) : "—"
                }
                tone={routism?.accuracy != null ? "good" : "neutral"}
              />
              <Card
                label="Zero-Router accuracy"
                value={
                  zeroRouter?.accuracy != null
                    ? formatPct(zeroRouter.accuracy)
                    : "—"
                }
              />
              <Card
                label="Token overhead"
                value={overhead != null ? `${overhead.toFixed(2)}×` : "—"}
                tone={
                  overhead != null && overhead > 1.5 ? "warn" : "neutral"
                }
              />
              <Card
                label="Win / loss / tie"
                value={
                  routism
                    ? `${routism.wins ?? 0}/${routism.losses ?? 0}/${routism.ties ?? 0}`
                    : "—"
                }
              />
            </div>

            <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-4">
              <Card
                label="Routism in tokens"
                value={
                  routism?.input_tokens != null
                    ? routism.input_tokens.toLocaleString()
                    : "—"
                }
              />
              <Card
                label="Routism out tokens"
                value={
                  routism?.output_tokens != null
                    ? routism.output_tokens.toLocaleString()
                    : "—"
                }
              />
              <Card
                label="Zero-Router tokens"
                value={
                  zeroRouter?.input_tokens != null
                    ? (
                        zeroRouter.input_tokens +
                        (zeroRouter.output_tokens ?? 0)
                      ).toLocaleString()
                    : "—"
                }
              />
              <Card
                label="Eval tasks"
                value={
                  routism?.total != null
                    ? `${routism.ok ?? 0}/${routism.total}`
                    : "—"
                }
              />
            </div>

            {verdict && (
              <div className="card mt-3 p-4 text-sm leading-relaxed">
                <span className="text-[var(--muted)]">verdict · </span>
                {verdict}
              </div>
            )}

            {records.length > 0 && (
              <div className="mt-5">
                <p className="mb-2 text-xs text-[var(--muted)]">Per-task results</p>
                <ul className="card divide-y divide-[var(--border)] overflow-hidden">
                  {records.map((r, i) => (
                    <li
                      key={`${r.task_id}-${i}`}
                      className="flex items-start gap-3 px-3 py-2.5 text-xs"
                    >
                      <StatusDot status={r.ok ? "up" : "down"} />
                      <div className="min-w-0 flex-1">
                        <p className="font-medium">
                          {r.task_id}{" "}
                          <span className="font-normal text-[var(--muted)]">
                            ({r.system_name})
                          </span>
                        </p>
                        <p className="break-words text-[var(--muted)]">{r.query}</p>
                        {r.error && (
                          <p className="text-[var(--bad)]">error: {r.error}</p>
                        )}
                      </div>
                      <div className="shrink-0 text-right text-[var(--muted)]">
                        <p>{r.input_tokens + r.output_tokens} tok</p>
                        <p>{r.latency_ms} ms</p>
                      </div>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </>
        )}
      </div>
    </section>
  );
}

function Card({
  label,
  value,
  tone = "neutral",
}: {
  label: string;
  value: string;
  tone?: "neutral" | "good" | "warn" | "bad";
}) {
  const border =
    tone === "good"
      ? "border-l-[var(--good)]"
      : tone === "warn"
        ? "border-l-[var(--warn)]"
        : tone === "bad"
          ? "border-l-[var(--bad)]"
          : "border-l-transparent";
  return (
    <div className={`card border-l-4 p-4 ${border}`}>
      <p className="text-xs font-medium uppercase tracking-wide text-[var(--muted)]">
        {label}
      </p>
      <p className="mt-1.5 break-all text-sm font-semibold">{value}</p>
    </div>
  );
}

type MetricsRoutismEval = {
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
type MetricsZeroRouterEval = {
  accuracy?: number;
  input_tokens?: number;
  output_tokens?: number;
  latency_ms?: number;
};
type EvalRecord = {
  task_id: string;
  query: string;
  system_name: string;
  answer: string;
  input_tokens: number;
  output_tokens: number;
  latency_ms: number;
  ok: boolean;
  error: string | null;
};

function formatPct(x: number): string {
  const pct = x <= 1 ? x * 100 : x;
  return `${pct.toFixed(0)}%`;
}

function formatTs(unix: number): string {
  try {
    return new Date(unix * 1000).toLocaleString();
  } catch {
    return String(unix);
  }
}
