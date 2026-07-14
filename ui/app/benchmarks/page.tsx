"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import {
  listBenchmarkSeeds,
  getBenchmarkStatus,
  listBenchmarkResults,
  getBenchmarkResult,
  startBenchmarkRun,
  type BenchmarkSeed,
  type BenchmarkStatus,
  type BenchmarkResultMeta,
  type BenchmarkSummary,
} from "@/lib/api";
import {
  PageHeader,
  Skeleton,
  ErrorState,
  EmptyState,
  Badge,
} from "../_components/status";

function fmtPct(n: number | undefined | null): string {
  if (n == null || Number.isNaN(n)) return "—";
  return `${(n * 100).toFixed(0)}%`;
}

function fmtNum(n: number | undefined | null, digits = 2): string {
  if (n == null || Number.isNaN(n)) return "—";
  return Number(n).toFixed(digits);
}

function shipTone(ship: string | boolean | undefined): "good" | "bad" | "warn" | "neutral" {
  if (ship === true || ship === "YES" || ship === "yes") return "good";
  if (ship === false || ship === "NO" || ship === "no") return "bad";
  return "neutral";
}

function SummaryCards({ summary }: { summary: BenchmarkSummary }) {
  const ship = summary.SHIP;
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
      <div className="card p-4">
        <p className="text-xs text-[var(--muted)]">SHIP</p>
        <p className="mt-1 text-lg font-semibold">
          <Badge tone={shipTone(ship)}>{String(ship ?? "—")}</Badge>
        </p>
      </div>
      <div className="card p-4">
        <p className="text-xs text-[var(--muted)]">Win rate vs best solo</p>
        <p className="mt-1 text-2xl font-semibold tabular-nums">{fmtPct(summary.win_rate)}</p>
      </div>
      <div className="card p-4">
        <p className="text-xs text-[var(--muted)]">Mean delta</p>
        <p className="mt-1 text-2xl font-semibold tabular-nums">
          {summary.mean_delta != null && summary.mean_delta > 0 ? "+" : ""}
          {fmtNum(summary.mean_delta)}
        </p>
      </div>
      <div className="card p-4">
        <p className="text-xs text-[var(--muted)]">Conductor / best solo</p>
        <p className="mt-1 text-lg font-semibold tabular-nums">
          {fmtNum(summary.mean_conductor_score)}{" "}
          <span className="text-sm font-normal text-[var(--muted)]">
            / {fmtNum(summary.mean_max_worker_score)}
          </span>
        </p>
      </div>
    </div>
  );
}

function ResultsTable({ summary }: { summary: BenchmarkSummary }) {
  const rows = summary.rows || [];
  const workerIds = useMemo(() => {
    const ids = new Set<string>();
    for (const r of rows) {
      Object.keys(r.worker_scores || {}).forEach((k) => ids.add(k));
    }
    if (summary.worker_ids) summary.worker_ids.forEach((w) => ids.add(w));
    return Array.from(ids);
  }, [rows, summary.worker_ids]);

  if (!rows.length) {
    // Fallback: mean scores only
    const means = summary.mean_scores || {};
    const entries = Object.entries(means);
    if (!entries.length) {
      return (
        <EmptyState title="No per-task rows">
          This result file has summaries only. Open raw JSON for full detail.
        </EmptyState>
      );
    }
    return (
      <div className="card overflow-x-auto p-0">
        <table className="w-full min-w-[480px] text-left text-sm">
          <thead>
            <tr className="border-b border-[var(--border)] text-xs text-[var(--muted)]">
              <th className="px-4 py-2 font-medium">Mode</th>
              <th className="px-4 py-2 font-medium">Mean score</th>
            </tr>
          </thead>
          <tbody>
            {entries.map(([k, v]) => (
              <tr key={k} className="border-b border-[var(--border)] last:border-0">
                <td className="px-4 py-2 font-mono text-xs">{k}</td>
                <td className="px-4 py-2 tabular-nums">{fmtNum(v as number)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }

  return (
    <div className="card overflow-x-auto p-0">
      <table className="w-full min-w-[640px] text-left text-sm">
        <thead>
          <tr className="border-b border-[var(--border)] text-xs text-[var(--muted)]">
            <th className="px-3 py-2 font-medium">Task</th>
            {workerIds.map((w) => (
              <th key={w} className="px-3 py-2 font-medium">
                {w}
              </th>
            ))}
            <th className="px-3 py-2 font-medium">Conductor</th>
            <th className="px-3 py-2 font-medium">Best solo</th>
            <th className="px-3 py-2 font-medium">Winner</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const c = r.conductor_score ?? r.conductor;
            const maxSolo = r.max_solo;
            const beat =
              c != null && maxSolo != null && Number(c) > Number(maxSolo);
            return (
              <tr key={r.task_id} className="border-b border-[var(--border)] last:border-0">
                <td className="px-3 py-2 font-mono text-xs">{r.task_id}</td>
                {workerIds.map((w) => (
                  <td key={w} className="px-3 py-2 tabular-nums text-xs">
                    {fmtNum((r.worker_scores || {})[w], 2)}
                  </td>
                ))}
                <td
                  className={`px-3 py-2 tabular-nums text-xs font-medium ${
                    beat ? "text-[var(--good)]" : ""
                  }`}
                >
                  {fmtNum(c, 2)}
                </td>
                <td className="px-3 py-2 tabular-nums text-xs">{fmtNum(maxSolo, 2)}</td>
                <td className="px-3 py-2 text-xs">
                  {r.winner || (beat ? "conductor" : "—")}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export default function BenchmarksPage() {
  const [seeds, setSeeds] = useState<BenchmarkSeed[]>([]);
  const [seedId, setSeedId] = useState("northstar");
  const [mode, setMode] = useState("all");
  const [limit, setLimit] = useState(4);
  const [timeoutS, setTimeoutS] = useState(600);
  const [status, setStatus] = useState<BenchmarkStatus | null>(null);
  const [history, setHistory] = useState<BenchmarkResultMeta[]>([]);
  const [view, setView] = useState<BenchmarkSummary | null>(null);
  const [viewName, setViewName] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const [loadingHist, setLoadingHist] = useState(true);
  const logEndRef = useRef<HTMLDivElement | null>(null);
  const logBoxRef = useRef<HTMLPreElement | null>(null);
  const stickToBottom = useRef(true);

  const refreshHistory = useCallback(async () => {
    try {
      const r = await listBenchmarkResults();
      setHistory(r.results || []);
    } catch {
      /* ignore */
    } finally {
      setLoadingHist(false);
    }
  }, []);

  const refreshStatus = useCallback(async () => {
    try {
      const s = await getBenchmarkStatus();
      setStatus(s);
      if (s.status === "done" && s.summary) {
        setView(s.summary);
        setViewName(s.result_path?.split("/").pop() || "latest");
        refreshHistory();
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [refreshHistory]);

  useEffect(() => {
    listBenchmarkSeeds()
      .then((r) => setSeeds(r.seeds || []))
      .catch(() => {});
    refreshHistory();
    refreshStatus();
  }, [refreshHistory, refreshStatus]);

  // Poll frequently while running so logs feel live
  useEffect(() => {
    if (status?.status !== "running") return;
    const t = setInterval(() => {
      refreshStatus();
    }, 1000);
    return () => clearInterval(t);
  }, [status?.status, refreshStatus]);

  // Auto-scroll log to bottom when new lines arrive (unless user scrolled up)
  useEffect(() => {
    if (!stickToBottom.current) return;
    const el = logBoxRef.current;
    if (el) {
      el.scrollTop = el.scrollHeight;
    } else {
      logEndRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
    }
  }, [status?.log?.length, status?.status]);

  async function onRun() {
    setError(null);
    setStarting(true);
    setView(null);
    try {
      await startBenchmarkRun({
        seed: seedId,
        mode,
        limit: mode === "dry-run" ? limit : limit,
        timeout_s: timeoutS,
      });
      await refreshStatus();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setStarting(false);
    }
  }

  async function onOpenResult(name: string) {
    setError(null);
    try {
      const r = await getBenchmarkResult(name);
      setView(r.summary);
      setViewName(r.name);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  const running = status?.status === "running" || starting;

  return (
    <section className="fade-up space-y-6">
      <PageHeader
        title="Benchmarks"
        description="Run NORTHSTAR: Conductor vs each worker alone. Target — win ≥70% vs best solo, mean delta ≥ +0.3."
        action={
          <Link href="/providers" className="btn btn-secondary !text-xs">
            Providers
          </Link>
        }
      />

      {error && <ErrorState message={error} />}

      {/* Run controls */}
      <div className="card p-5 space-y-4">
        <h2 className="text-sm font-semibold">Run a benchmark</h2>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <label className="text-xs font-medium text-[var(--muted)]">
            Suite
            <select
              className="field mt-1"
              value={seedId}
              onChange={(e) => setSeedId(e.target.value)}
              disabled={running}
            >
              {(seeds.length ? seeds : [
                { id: "northstar", name: "NORTHSTAR (hard multi-step)", n_tasks: 7 },
                { id: "full", name: "Full seed suite", n_tasks: 20 },
              ]).map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                  {s.n_tasks != null ? ` (${s.n_tasks} tasks)` : ""}
                </option>
              ))}
            </select>
          </label>
          <label className="text-xs font-medium text-[var(--muted)]">
            Mode
            <select
              className="field mt-1"
              value={mode}
              onChange={(e) => setMode(e.target.value)}
              disabled={running}
            >
              <option value="all">All (each solo + Conductor)</option>
              <option value="conductor">Conductor only</option>
              <option value="dry-run">Dry-run (plans only, no APIs)</option>
            </select>
          </label>
          <label className="text-xs font-medium text-[var(--muted)]">
            Task limit
            <input
              type="number"
              min={1}
              max={50}
              className="field mt-1"
              value={limit}
              onChange={(e) => setLimit(Number(e.target.value) || 1)}
              disabled={running}
            />
          </label>
          <label className="text-xs font-medium text-[var(--muted)]">
            Timeout / call (s)
            <input
              type="number"
              min={30}
              max={3600}
              className="field mt-1"
              value={timeoutS}
              onChange={(e) => setTimeoutS(Number(e.target.value) || 600)}
              disabled={running}
            />
          </label>
        </div>
        <p className="text-xs text-[var(--muted)]">
          Live <strong>all</strong> mode calls every provider alone, then Conductor, for each task.
          With 5 workers and limit 4 this can take a long time. Use dry-run to smoke the suite offline.
        </p>
        <button
          type="button"
          className="btn btn-primary"
          onClick={onRun}
          disabled={running}
        >
          {running ? "Running…" : "Start benchmark"}
        </button>
      </div>

      {/* Live status + streaming log */}
      {status && status.status !== "idle" && (
        <div className="card p-5 space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="text-sm font-semibold">Job status</h2>
            <Badge
              tone={
                status.status === "done"
                  ? "good"
                  : status.status === "error"
                    ? "bad"
                    : status.status === "running"
                      ? "warn"
                      : "neutral"
              }
            >
              {status.status}
            </Badge>
            {status.status === "running" && (
              <span className="inline-flex items-center gap-1.5 text-xs text-[var(--warn)]">
                <span className="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-[var(--warn)]" />
                live log · {(status.log || []).length} lines · polls every 1s
              </span>
            )}
            {(status.log || []).length > 0 && status.status !== "running" && (
              <span className="text-xs text-[var(--muted)]">
                {(status.log || []).length} log lines
              </span>
            )}
          </div>
          {status.progress && (
            <p className="rounded-[var(--radius-sm)] border border-[var(--border)] bg-[var(--background)] px-3 py-2 font-mono text-xs text-[var(--foreground)]">
              {status.progress}
            </p>
          )}
          {status.error && (
            <p className="rounded-[var(--radius-sm)] border border-[var(--bad-border)] bg-[var(--bad-bg)] p-3 text-sm text-[var(--bad)]">
              {status.error}
            </p>
          )}
          {status.result_path && (
            <p className="text-xs text-[var(--muted)]">
              Saved: <code className="font-mono">{status.result_path}</code>
            </p>
          )}
          {(status.log || []).length > 0 ? (
            <pre
              ref={logBoxRef}
              onScroll={(e) => {
                const el = e.currentTarget;
                const dist =
                  el.scrollHeight - el.scrollTop - el.clientHeight;
                stickToBottom.current = dist < 48;
              }}
              className="max-h-[min(28rem,50vh)] min-h-[12rem] overflow-auto rounded-[var(--radius-sm)] border border-[var(--border)] bg-[var(--background)] p-3 text-[11px] leading-relaxed text-[var(--muted)]"
            >
              {(status.log || []).join("\n")}
              <div ref={logEndRef} />
            </pre>
          ) : status.status === "running" ? (
            <p className="text-xs text-[var(--muted)]">Waiting for first log line…</p>
          ) : null}
        </div>
      )}

      {/* Active / selected results */}
      {view && (
        <div className="space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 className="section-label !mb-0">
              Results{viewName ? `: ${viewName}` : ""}
            </h2>
            <span className="text-xs text-[var(--muted)]">
              {view.n_tasks ?? view.seed?.n_tasks ?? "?"} tasks
              {view.worker_ids?.length
                ? ` · ${view.worker_ids.join(", ")}`
                : ""}
            </span>
          </div>
          <SummaryCards summary={view} />
          <ResultsTable summary={view} />
        </div>
      )}

      {/* History */}
      <div className="space-y-3">
        <h2 className="section-label">Past runs</h2>
        {loadingHist ? (
          <Skeleton className="h-24 w-full" />
        ) : history.length === 0 ? (
          <EmptyState title="No saved results yet">
            Start a benchmark above. JSON files also live in{" "}
            <code className="text-xs">eval_results/</code>.
          </EmptyState>
        ) : (
          <ul className="space-y-2">
            {history.map((h) => (
              <li key={h.name}>
                <button
                  type="button"
                  onClick={() => onOpenResult(h.name)}
                  className="card flex w-full flex-wrap items-center justify-between gap-2 p-3 text-left transition-colors hover:bg-[var(--card-hover)]"
                >
                  <div className="min-w-0">
                    <p className="truncate font-mono text-xs font-medium">{h.name}</p>
                    <p className="mt-0.5 text-xs text-[var(--muted)]">
                      {h.kind || "—"} · {h.n_tasks ?? "?"} tasks ·{" "}
                      {h.mtime ? new Date(h.mtime).toLocaleString() : ""}
                    </p>
                  </div>
                  <div className="flex shrink-0 items-center gap-2 text-xs">
                    {h.SHIP != null && (
                      <Badge tone={shipTone(h.SHIP)}>{String(h.SHIP)}</Badge>
                    )}
                    {h.win_rate != null && (
                      <span className="tabular-nums text-[var(--muted)]">
                        win {fmtPct(h.win_rate)}
                      </span>
                    )}
                    {h.mean_delta != null && (
                      <span className="tabular-nums text-[var(--muted)]">
                        Δ {h.mean_delta > 0 ? "+" : ""}
                        {fmtNum(h.mean_delta)}
                      </span>
                    )}
                  </div>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}
