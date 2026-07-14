"use client";

import { useCallback, useEffect, useState } from "react";
import {
  createKey,
  getStoredApiKey,
  listKeys,
  revokeKey,
  setStoredApiKey,
  type ApiKeyMeta,
  type KeysList,
} from "@/lib/auth";
import { PageHeader, Badge, EmptyState, ErrorState } from "../_components/status";
import CopyButton from "../_components/copy-button";

export default function KeysPage() {
  const [data, setData] = useState<KeysList | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [name, setName] = useState("agent");
  const [onceSecret, setOnceSecret] = useState<string | null>(null);
  const [stored, setStored] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setErr(null);
    setStored(getStoredApiKey());
    try {
      const k = await listKeys();
      setData(k);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  async function onCreate() {
    setBusy(true);
    setErr(null);
    setOnceSecret(null);
    try {
      const res = await createKey(name.trim() || "default");
      setOnceSecret(res.secret);
      setStoredApiKey(res.secret);
      setStored(res.secret);
      await refresh();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function onRevoke(k: ApiKeyMeta) {
    if (!confirm(`Revoke “${k.name}” (${k.key_prefix})? Agents using it will get 401.`)) {
      return;
    }
    setBusy(true);
    try {
      await revokeKey(k.id);
      await refresh();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  const baseUrl = data?.base_url ?? "http://localhost:8000/v1";
  const model = data?.model ?? "routism-ultra";

  return (
    <div className="space-y-8">
      <PageHeader
        title="API keys"
        description="Keys for coding agents. No account login — keys belong to this installation. Secret is shown once."
      />

      {err && <ErrorState message={err} />}

      {onceSecret && (
        <div className="space-y-2 rounded-[var(--radius)] border border-[var(--warn-border)] bg-[var(--warn-bg)] p-4">
          <p className="text-sm font-semibold text-[var(--warn)]">
            Copy your secret now — it will not be shown again
          </p>
          <div className="flex flex-wrap items-center gap-2">
            <code className="break-all rounded bg-[var(--card)] px-2 py-1 text-xs">
              {onceSecret}
            </code>
            <CopyButton value={onceSecret} label="Copy secret" />
          </div>
        </div>
      )}

      {stored && (
        <p className="text-xs text-[var(--muted)]">
          Browser is using a stored key for dashboard calls ({stored.slice(0, 10)}…).
        </p>
      )}

      <section className="space-y-4 rounded-[var(--radius)] border border-[var(--border)] bg-[var(--card)] p-5">
        <h2 className="text-sm font-semibold">Create key</h2>
        <div className="flex flex-wrap gap-2">
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Key name"
            className="min-w-[12rem] flex-1 rounded-[var(--radius-sm)] border border-[var(--border)] bg-[var(--background-elevated)] px-3 py-2 text-sm"
          />
          <button
            type="button"
            disabled={busy}
            onClick={onCreate}
            className="rounded-[var(--radius-pill)] bg-[var(--accent)] px-4 py-2 text-sm font-medium text-[var(--accent-text)] disabled:opacity-60"
          >
            Create key
          </button>
        </div>
      </section>

      <section className="space-y-3">
        <h2 className="text-sm font-semibold">Active keys</h2>
        {!data?.keys?.length ? (
          <EmptyState title="No keys yet">
            Create a key above, then set it as OPENAI_API_KEY in your agent.
          </EmptyState>
        ) : (
          <ul className="divide-y divide-[var(--border)] rounded-[var(--radius)] border border-[var(--border)] bg-[var(--card)]">
            {data.keys.map((k) => (
              <li
                key={k.id}
                className="flex flex-wrap items-center justify-between gap-3 px-4 py-3 text-sm"
              >
                <div>
                  <div className="font-medium">{k.name}</div>
                  <div className="text-xs text-[var(--muted)]">
                    {k.key_prefix} · created{" "}
                    {new Date(k.created_at * 1000).toLocaleString()}
                  </div>
                </div>
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => onRevoke(k)}
                  className="rounded-[var(--radius-pill)] border border-[var(--bad-border)] px-3 py-1 text-xs font-medium text-[var(--bad)]"
                >
                  Revoke
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="space-y-3 rounded-[var(--radius)] border border-[var(--border)] bg-[var(--card)] p-5">
        <div className="flex items-center gap-2">
          <h2 className="text-sm font-semibold">Agent quickstart</h2>
          <Badge tone="good">OpenAI-compatible</Badge>
        </div>
        <div className="space-y-2 text-xs">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-[var(--muted)]">Base URL</span>
            <code className="rounded bg-[var(--background)] px-2 py-1">{baseUrl}</code>
            <CopyButton value={baseUrl} label="Copy" />
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-[var(--muted)]">Model</span>
            <code className="rounded bg-[var(--background)] px-2 py-1">{model}</code>
            <CopyButton value={model} label="Copy" />
          </div>
          <pre className="overflow-x-auto rounded-[var(--radius-sm)] bg-[var(--background)] p-3 text-[11px] leading-relaxed">
{`export OPENAI_BASE_URL="${baseUrl}"
export OPENAI_API_KEY="rtm_…"
# model: ${model}
# Use long timeouts (5–10 min) — orchestration is multi-step.`}
          </pre>
        </div>
      </section>
    </div>
  );
}
