"use client";

import Link from "next/link";
import { Badge } from "./_components/status";

export default function Home() {
  return (
    <div className="space-y-14">
      <section className="space-y-6 pt-4 text-center sm:pt-8">
        <Badge tone="good">OpenAI-compatible · self-hosted</Badge>
        <h1
          className="mx-auto max-w-2xl text-4xl font-semibold tracking-tight sm:text-5xl"
          style={{ fontFamily: "var(--font-display)" }}
        >
          Multi-model orchestration for coding agents
        </h1>
        <p className="mx-auto max-w-xl text-base leading-relaxed text-[var(--muted)] sm:text-lg">
          Point Hermes, Cursor, or any OpenAI SDK at Routism. Bring your own
          model providers. No accounts, no cloud lock-in.
        </p>
        <div className="flex flex-wrap items-center justify-center gap-3">
          <Link
            href="/providers"
            className="rounded-[var(--radius-pill)] bg-[var(--accent)] px-5 py-2.5 text-sm font-medium text-[var(--accent-text)]"
          >
            Connect providers
          </Link>
          <Link
            href="/keys"
            className="rounded-[var(--radius-pill)] border border-[var(--border)] bg-[var(--card)] px-5 py-2.5 text-sm font-medium"
          >
            API keys
          </Link>
        </div>
      </section>

      <section className="grid gap-4 sm:grid-cols-3">
        {[
          {
            title: "1. Providers",
            body: "Add Ollama, MLX, or cloud OpenAI-compatible endpoints (up to 5).",
            href: "/providers",
          },
          {
            title: "2. API key",
            body: "Create a rtm_… key for your agent. Shown once; revoke anytime.",
            href: "/keys",
          },
          {
            title: "3. Agent",
            body: "Base URL …/v1, model routism-ultra, long client timeouts.",
            href: "/keys",
          },
        ].map((c) => (
          <Link
            key={c.title}
            href={c.href}
            className="rounded-[var(--radius)] border border-[var(--border)] bg-[var(--card)] p-5 shadow-[var(--shadow-sm)] transition hover:bg-[var(--card-hover)]"
          >
            <h2 className="text-base font-semibold">{c.title}</h2>
            <p className="mt-2 text-sm text-[var(--muted)]">{c.body}</p>
          </Link>
        ))}
      </section>

      <section className="rounded-[var(--radius)] border border-[var(--border)] bg-[var(--card)] p-6">
        <h2 className="text-sm font-semibold">Quick env</h2>
        <pre className="mt-3 overflow-x-auto rounded-[var(--radius-sm)] bg-[var(--background)] p-4 text-xs">
{`export OPENAI_BASE_URL="http://localhost:8000/v1"
export OPENAI_API_KEY="rtm_…"
# model: routism-ultra`}
        </pre>
      </section>
    </div>
  );
}
