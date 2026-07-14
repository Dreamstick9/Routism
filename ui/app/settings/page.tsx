"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  getSettings,
  putSettings,
  getPool,
  filterReservedWorkers,
  type Settings,
  type SettingsUpdate,
  type PoolResponse,
} from "@/lib/api";
import {
  Skeleton,
  ErrorState,
  Badge,
  PageHeader,
} from "../_components/status";

const MEMORY_BACKENDS = ["inprocess", "file", "sqlite"] as const;

export default function SettingsPage() {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [pool, setPool] = useState<PoolResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [draft, setDraft] = useState<SettingsUpdate>({});

  useEffect(() => {
    let active = true;
    (async () => {
      setLoading(true);
      setError(null);
      try {
        const [s, p] = await Promise.all([getSettings(), getPool()]);
        if (!active) return;
        setSettings(s);
        setPool(p);
        setDraft({
          max_repairs: s.max_repairs,
          max_total_tokens: s.max_total_tokens,
          memory_backend: s.memory_backend,
          memory_scope: s.memory_scope,
          orchestrator_worker_id: s.orchestrator_worker_id ?? null,
          verifier_worker_id: s.verifier_worker_id ?? null,
        });
      } catch (e) {
        if (active) {
          const msg = e instanceof Error ? e.message : String(e);
          setError(
            msg.includes("401")
              ? "Settings are gated behind MANAGEMENT_API_KEY. Set it in the server env, or access the dashboard from loopback (127.0.0.1)."
              : `Could not load settings: ${msg}`,
          );
        }
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => {
      active = false;
    };
  }, []);

  async function onSave() {
    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      await putSettings(draft);
      const s = await getSettings();
      setSettings(s);
      setDraft({
        max_repairs: s.max_repairs,
        max_total_tokens: s.max_total_tokens,
        memory_backend: s.memory_backend,
        memory_scope: s.memory_scope,
        orchestrator_worker_id: s.orchestrator_worker_id ?? null,
        verifier_worker_id: s.verifier_worker_id ?? null,
      });
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  }

  function onReset() {
    if (!settings) return;
    setDraft({
      max_repairs: settings.max_repairs,
      max_total_tokens: settings.max_total_tokens,
      memory_backend: settings.memory_backend,
      memory_scope: settings.memory_scope,
      orchestrator_worker_id: settings.orchestrator_worker_id ?? null,
      verifier_worker_id: settings.verifier_worker_id ?? null,
    });
    setError(null);
    setSaved(false);
  }

  const dirty =
    settings != null &&
    (draft.max_repairs !== settings.max_repairs ||
      draft.max_total_tokens !== settings.max_total_tokens ||
      draft.memory_backend !== settings.memory_backend ||
      draft.memory_scope !== settings.memory_scope ||
      (draft.orchestrator_worker_id ?? null) !==
        (settings.orchestrator_worker_id ?? null) ||
      (draft.verifier_worker_id ?? null) !== (settings.verifier_worker_id ?? null));

  return (
    <section className="fade-up space-y-6">
      <PageHeader
        title="Settings"
        description={
          <>
            Global orchestrator knobs for every plan workflow. Per-provider config
            lives in{" "}
            <Link
              href="/providers"
              className="font-medium text-[var(--accent)] underline"
            >
              Providers
            </Link>
            .
          </>
        }
      />

      {loading ? (
        <div className="space-y-3">
          <Skeleton className="h-16 w-full" />
          <Skeleton className="h-16 w-full" />
          <Skeleton className="h-16 w-full" />
        </div>
      ) : error && !settings ? (
        <ErrorState message={error} />
      ) : settings ? (
        <div className="card-soft max-w-xl space-y-5 p-5">
          {error && <ErrorState message={error} />}

          <Field
            label="Max repairs"
            hint="Per-step verifier repair attempts before re-routing to the next-best worker."
          >
            <input
              type="number"
              min={0}
              value={draft.max_repairs ?? 0}
              onChange={(e) =>
                setDraft({ ...draft, max_repairs: parseNum(e.target.value) })
              }
              className="field w-32"
            />
          </Field>

          <Field
            label="Max total tokens"
            hint="Per-query token budget. The executor aborts before an unaffordable step and returns a partial answer."
          >
            <input
              type="number"
              min={0}
              value={draft.max_total_tokens ?? 0}
              onChange={(e) =>
                setDraft({
                  ...draft,
                  max_total_tokens: parseNum(e.target.value),
                })
              }
              className="field w-32"
            />
          </Field>

          <Field
            label="Memory backend"
            hint="Cross-query shared memory. inprocess is lost on restart; file is JSONL; sqlite is a local DB."
          >
            <select
              value={draft.memory_backend ?? "inprocess"}
              onChange={(e) =>
                setDraft({
                  ...draft,
                  memory_backend: e.target.value as (typeof MEMORY_BACKENDS)[number],
                })
              }
              className="field w-40"
            >
              {MEMORY_BACKENDS.map((b) => (
                <option key={b} value={b}>
                  {b}
                </option>
              ))}
            </select>
          </Field>

          <Field
            label="Memory scope"
            hint="Namespace for cross-query scope-refs (access_list shape scope:<id>:s:<idx>)."
          >
            <input
              type="text"
              value={draft.memory_scope ?? ""}
              onChange={(e) =>
                setDraft({ ...draft, memory_scope: e.target.value })
              }
              placeholder="default"
              className="field max-w-xs"
            />
          </Field>

          <div className="border-t border-[var(--border)] pt-4">
            <h2 className="text-sm font-semibold">Role assignments</h2>
            <p className="mt-0.5 text-xs leading-relaxed text-[var(--muted)]">
              Pin the Plan conductor and verifier to specific providers. Leave empty
              to let the engine pick. These are pool roles — not the hidden engine
              models.
            </p>
          </div>

          <Field
            label="Orchestrator (conductor)"
            hint="Writes multi-step workflows. If unset, plan mode may fail — no silent workers[0] fallback."
          >
            <RolePicker
              value={draft.orchestrator_worker_id ?? null}
              pool={pool}
              onChange={(id) =>
                setDraft({ ...draft, orchestrator_worker_id: id })
              }
              noneLabel="— none —"
            />
          </Field>

          <Field
            label="Verifier"
            hint="Optional ACCEPT/REJECT gate on step outputs. When unset, steps run without a verifier."
          >
            <RolePicker
              value={draft.verifier_worker_id ?? null}
              pool={pool}
              onChange={(id) => setDraft({ ...draft, verifier_worker_id: id })}
              noneLabel="— none (no verifier) —"
            />
          </Field>

          <div className="flex flex-wrap items-center gap-2.5 border-t border-[var(--border)] pt-4">
            <button
              onClick={onSave}
              disabled={!dirty || saving}
              className="btn btn-primary"
            >
              {saving ? "Saving…" : "Save settings"}
            </button>
            <button
              onClick={onReset}
              disabled={!dirty || saving}
              className="btn btn-secondary"
            >
              Reset
            </button>
            {dirty && <Badge tone="warn">unsaved changes</Badge>}
            {saved && <Badge tone="good">saved</Badge>}
          </div>

          <p className="text-xs leading-relaxed text-[var(--muted)]">
            Settings persist to{" "}
            <code className="rounded bg-[var(--border)] px-1.5 py-0.5">
              routism.yaml
            </code>{" "}
            on the server. Adding or removing providers does not reset these values.
          </p>
        </div>
      ) : null}
    </section>
  );
}

function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <label className="block">
      <span className="text-sm font-medium">{label}</span>
      {hint && (
        <p className="mt-0.5 text-xs leading-relaxed text-[var(--muted)]">{hint}</p>
      )}
      <div className="mt-1.5">{children}</div>
    </label>
  );
}

function parseNum(s: string): number {
  const n = parseInt(s, 10);
  return Number.isFinite(n) ? Math.max(0, n) : 0;
}

function RolePicker({
  value,
  pool,
  onChange,
  noneLabel,
}: {
  value: string | null;
  pool: PoolResponse | null;
  onChange: (id: string | null) => void;
  noneLabel: string;
}) {
  const options = filterReservedWorkers(pool);
  return (
    <select
      value={value ?? ""}
      onChange={(e) => onChange(e.target.value || null)}
      disabled={!options.length}
      className="field max-w-xs disabled:opacity-50"
    >
      <option value="">{noneLabel}</option>
      {options.map((w) => (
        <option key={w.id} value={w.id}>
          {w.id} ({w.model})
        </option>
      ))}
    </select>
  );
}
