"use client";

import Nav from "@/components/Nav";
import SkipLink from "@/components/SkipLink";
import FooterRed from "@/components/FooterRed";
import TerminalDemo from "@/components/TerminalDemo";
import CopyButton from "@/components/CopyButton";
import SmoothScroll from "@/components/SmoothScroll";
import {
  AGENT_ENV_SNIPPET,
  DASHBOARD_URL,
  ENGINE_VS_WORKERS,
  GITHUB_DOCS_API,
  GITHUB_DOCS_OPENAI,
  GITHUB_URL,
  INSTALL_COMMAND,
  INSTALL_SNIPPET,
  MODEL_ID,
  NO_ACCOUNTS_CLAIM,
  PRODUCT_HOOK,
  PRODUCT_ONE_LINER,
  PROOF_CARDS,
  API_V1_BASE,
} from "@/lib/product-facts";
import { track } from "@/lib/analytics";

export default function HomePage() {
  return (
    <SmoothScroll>
      <SkipLink />
      <Nav />

      <main id="main">
        {/* WORLD — solid red hero, no Three.js */}
        <section
          id="world"
          data-chapter
          className="relative flex min-h-screen flex-col items-center justify-center overflow-hidden bg-[var(--signal,#E31C23)] px-6 pb-24 pt-28 text-center"
          aria-label="Hero"
        >
          {/* Optional crop word at edge */}
          <div
            className="pointer-events-none absolute bottom-0 left-0 right-0 overflow-hidden select-none"
            aria-hidden
          >
            <p
              className="translate-y-[35%] whitespace-nowrap text-center font-bold leading-none tracking-[-0.06em] text-white/10"
              style={{ fontSize: "clamp(6rem, 22vw, 18rem)" }}
            >
              ROUTISM
            </p>
          </div>

          <div className="relative z-[1] mx-auto w-full max-w-4xl">
            <div
              className="mb-6 h-px w-full bg-[var(--rule-on-signal,rgba(255,255,255,0.18))]"
              aria-hidden
            />
            <p
              data-reveal
              className="mb-4 text-xs uppercase tracking-[0.35em] text-white/70"
            >
              Self-hosted
            </p>
            <h1
              data-reveal
              className="display-title max-w-4xl text-[var(--paper,#FFFFFF)]"
            >
              Conduct many models
              <br />
              as one API
            </h1>
            <div
              className="mt-6 h-px w-full bg-[var(--rule-on-signal,rgba(255,255,255,0.18))]"
              aria-hidden
            />
            <p
              data-reveal
              className="mt-6 max-w-xl mx-auto text-base leading-relaxed text-white/85 md:text-lg"
            >
              {PRODUCT_ONE_LINER}
            </p>
            <div
              data-reveal
              className="mt-10 flex flex-wrap items-center justify-center gap-3"
            >
              <a
                href={GITHUB_URL}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center justify-center rounded-full bg-[var(--charcoal,#1A1A1A)] px-6 py-3 text-sm font-bold text-[var(--paper,#FFFFFF)] transition-opacity hover:opacity-90 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white"
                data-cta="github-hero"
                data-github-url={GITHUB_URL}
                onClick={() => track("cta_github", { where: "hero" })}
              >
                Get Routism
              </a>
              <a
                href="#demo"
                className="inline-flex items-center justify-center rounded-full border border-white/30 px-6 py-3 text-sm font-semibold text-white transition-colors hover:bg-white/10 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white"
              >
                See install
              </a>
            </div>
            <p
              data-reveal
              className="mt-8 mono text-[10px] text-white/60 md:text-xs"
            >
              {INSTALL_COMMAND} → routism · model {MODEL_ID}
            </p>
          </div>
        </section>

        {/* HOOK / STORY */}
        <section
          id="hook"
          data-chapter
          className="section-pad mx-auto max-w-5xl border-t border-white/5"
          aria-labelledby="hook-title"
        >
          <p
            data-reveal
            className="text-xs uppercase tracking-[0.3em] text-[var(--pulse)]"
          >
            Story
          </p>
          <h2
            id="hook-title"
            data-reveal
            className="display-title mt-4 max-w-3xl"
          >
            {PRODUCT_HOOK}
          </h2>
          <p
            data-reveal
            className="mt-8 max-w-2xl text-lg leading-relaxed text-[var(--fog)]"
          >
            Coding agents speak OpenAI Chat Completions. Routism is that
            endpoint — then a{" "}
            <strong className="text-white">Conductor</strong> plans, fans work
            across your models, scores, and merges one answer.
          </p>
          <ul data-reveal className="mt-10 grid gap-4 sm:grid-cols-3">
            {["Plan", "Execute", "Merge"].map((label, i) => (
              <li key={label} className="glass rounded-xl px-5 py-6 text-left">
                <span className="mono text-xs text-[var(--filament)]">
                  0{i + 1}
                </span>
                <div className="mt-2 text-xl font-semibold">{label}</div>
              </li>
            ))}
          </ul>
        </section>

        {/* ENGINE ≠ WORKERS */}
        <section
          id="split"
          data-chapter
          className="section-pad border-t border-white/5"
          aria-labelledby="split-title"
        >
          <div className="mx-auto grid max-w-5xl gap-10 md:grid-cols-2 md:items-center">
            <div>
              <p
                data-reveal
                className="text-xs uppercase tracking-[0.3em] text-[var(--filament)]"
              >
                Architecture
              </p>
              <h2
                id="split-title"
                data-reveal
                className="mt-4 text-4xl font-bold tracking-tight md:text-5xl"
              >
                Engine ≠ Workers
              </h2>
              <p
                data-reveal
                className="mt-6 text-[var(--fog)] leading-relaxed"
              >
                {ENGINE_VS_WORKERS}
              </p>
              <p
                data-reveal
                className="mt-4 text-sm text-[var(--fog-dim)] leading-relaxed"
              >
                Hidden engine models (planner / verifier) live on{" "}
                <strong className="text-white">host Ollama</strong>. Your
                worker pool is BYOK — Ollama, MLX, Groq, or any OpenAI-compatible
                endpoint. The CLI wires{" "}
                <code className="mono text-[var(--filament)]">
                  OLLAMA_BASE_URL
                </code>{" "}
                so Docker can reach host Ollama.
              </p>
            </div>
            <div data-reveal className="grid gap-4">
              <div className="glass rounded-2xl p-6">
                <div className="text-xs uppercase tracking-widest text-[var(--pulse)]">
                  Engine
                </div>
                <div className="mt-2 font-semibold">Conductor brains</div>
                <p className="mt-2 text-sm text-[var(--fog-dim)]">
                  eng-thinker · eng-verifier · eng-judge2 via Ollama — not in
                  the Docker image, not selectable as workers.
                </p>
              </div>
              <div className="glass rounded-2xl border-[var(--border-glow)] p-6">
                <div className="text-xs uppercase tracking-widest text-[var(--filament)]">
                  Workers
                </div>
                <div className="mt-2 font-semibold">Your pool (≤5)</div>
                <p className="mt-2 text-sm text-[var(--fog-dim)]">
                  Connect providers in the dashboard. Secrets stay on your
                  machine.
                </p>
              </div>
            </div>
          </div>
        </section>

        {/* INSTALL DEMO */}
        <section
          id="demo"
          data-chapter
          className="section-pad border-t border-white/5"
          aria-labelledby="demo-title"
        >
          <div className="mx-auto max-w-3xl text-center">
            <p
              data-reveal
              className="text-xs uppercase tracking-[0.3em] text-[var(--acid)]"
            >
              Install
            </p>
            <h2
              id="demo-title"
              data-reveal
              className="mt-4 display-title !text-4xl md:!text-5xl"
            >
              One CLI. Full stack.
            </h2>
            <p data-reveal className="mx-auto mt-4 max-w-xl text-[var(--fog)]">
              {NO_ACCOUNTS_CLAIM} Run{" "}
              <code className="mono text-[var(--filament)]">
                {INSTALL_COMMAND}
              </code>{" "}
              then bare <code className="mono text-white">routism</code> for
              interactive setup — Docker, Ollama, engine models, API + UI.
            </p>
          </div>
          <div data-reveal className="mt-12">
            <TerminalDemo />
          </div>
          <p
            data-reveal
            className="mx-auto mt-8 max-w-xl text-center text-sm text-[var(--fog-dim)]"
          >
            Dashboard{" "}
            <a
              className="text-[var(--filament)] underline-offset-2 hover:underline"
              href={DASHBOARD_URL}
            >
              {DASHBOARD_URL}
            </a>{" "}
            · API <span className="mono text-white">{API_V1_BASE}</span>
          </p>
        </section>

        {/* PROOF */}
        <section
          id="proof"
          data-chapter
          className="section-pad border-t border-white/5"
          aria-labelledby="proof-title"
        >
          <div className="mx-auto max-w-5xl">
            <p
              data-reveal
              className="text-xs uppercase tracking-[0.3em] text-[var(--fog-dim)]"
            >
              Why Routism
            </p>
            <h2
              id="proof-title"
              data-reveal
              className="mt-4 text-4xl font-bold tracking-tight"
            >
              Built for agents, not demos
            </h2>
            <div className="mt-10 grid gap-4 sm:grid-cols-2">
              {PROOF_CARDS.map((c) => (
                <article key={c.title} data-reveal className="card-proof">
                  <h3 className="text-lg font-semibold text-white">
                    {c.title}
                  </h3>
                  <p className="mt-2 text-sm leading-relaxed text-[var(--fog-dim)]">
                    {c.body}
                  </p>
                </article>
              ))}
            </div>
            <p data-reveal className="mt-8 text-sm text-[var(--fog-dim)]">
              Docs:{" "}
              <a
                href={GITHUB_DOCS_OPENAI}
                className="text-[var(--filament)] hover:underline"
                target="_blank"
                rel="noopener noreferrer"
              >
                OpenAI compat
              </a>
              {" · "}
              <a
                href={GITHUB_DOCS_API}
                className="text-[var(--filament)] hover:underline"
                target="_blank"
                rel="noopener noreferrer"
              >
                API reference
              </a>
            </p>
          </div>
        </section>

        {/* DOWNLOAD */}
        <section
          id="download"
          data-chapter
          className="section-pad border-t border-white/5"
          aria-labelledby="download-title"
        >
          <div className="mx-auto max-w-3xl text-center">
            <p
              data-reveal
              className="text-xs uppercase tracking-[0.3em] text-[var(--filament)]"
            >
              Get Routism
            </p>
            <h2 id="download-title" data-reveal className="display-title mt-4">
              Ready to host.
              <br />
              <span className="filament-text">Ready to run.</span>
            </h2>
            <p data-reveal className="mx-auto mt-6 max-w-lg text-[var(--fog)]">
              Clone the public MIT repo. Install the CLI. Conduct your models.
            </p>
            <div
              data-reveal
              className="mt-10 flex flex-wrap items-center justify-center gap-3"
            >
              <a
                href={GITHUB_URL}
                target="_blank"
                rel="noopener noreferrer"
                className="cta-primary"
                data-cta="github-download"
                data-github-url={GITHUB_URL}
                onClick={() => track("cta_github", { where: "download" })}
              >
                Star & clone on GitHub
              </a>
              <CopyButton
                text={INSTALL_COMMAND}
                label={`Copy ${INSTALL_COMMAND}`}
                event="copy_install_cmd"
              />
              <CopyButton
                text={INSTALL_SNIPPET}
                label="Copy full setup"
                event="copy_install"
              />
            </div>
            <pre
              data-reveal
              data-install-snippet={INSTALL_SNIPPET}
              className="glass mono mx-auto mt-10 max-w-xl overflow-x-auto rounded-xl p-4 text-left text-[11px] text-[var(--fog)]"
            >
              {INSTALL_SNIPPET}
            </pre>
            <p data-reveal className="mt-6 text-xs text-[var(--fog-dim)]">
              Agent model id:{" "}
              <span className="mono text-white">{MODEL_ID}</span>
              {" · "}
              env:{" "}
              <span className="mono">OPENAI_BASE_URL={API_V1_BASE}</span>
            </p>
          </div>
        </section>
      </main>

      <FooterRed />
      {/* keep agent env fact available for scrapers / tests consumers */}
      <span className="sr-only">{AGENT_ENV_SNIPPET}</span>
    </SmoothScroll>
  );
}
