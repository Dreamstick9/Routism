/**
 * Frozen presentational copy deck for the showcase.
 * Product-truth (URLs, commands, model ids, ports, claims) must come from
 * product-facts.ts — this module holds labels, display lines, and framing only.
 */
import { INSTALL_COMMAND, MODEL_ID } from "@/lib/product-facts";

/* -------------------------------------------------------------------------- */
/* Hero / world                                                                */
/* -------------------------------------------------------------------------- */

export const HERO_LABEL = "Self-hosted" as const;

/** Display H1 — two lines; matches shipped structure (not a new slogan). */
export const HERO_H1_LINES = ["Conduct many models", "as one API"] as const;

export const HERO_CROP = "ROUTISM" as const;

export const CTA_GET_ROUTISM = "Get Routism" as const;
export const CTA_SEE_INSTALL = "See install" as const;

/** Meta line under hero CTAs — facts interpolated. */
export function heroMetaLine(installCommand: string, modelId: string): string {
  return `${installCommand} → routism · model ${modelId}`;
}

/* -------------------------------------------------------------------------- */
/* Hook / story                                                                */
/* -------------------------------------------------------------------------- */

export const HOOK_LABEL = "Story" as const;

/** Stacked display lines (Plan / Execute / Merge phases). */
export const HOOK_STACK_LINES = ["Plan.", "Execute.", "Merge."] as const;

export const HOOK_BODY =
  "Coding agents speak OpenAI Chat Completions. Routism is that endpoint — then a Conductor plans, fans work across your models, scores, and merges one answer." as const;

/* -------------------------------------------------------------------------- */
/* Split / architecture                                                        */
/* -------------------------------------------------------------------------- */

export const SPLIT_LABEL = "Architecture" as const;
export const SPLIT_H2 = "Engine ≠ Workers" as const;

export const SPLIT_SUPPORT =
  "Hidden engine models (planner / verifier) live on host Ollama. Your worker pool is BYOK — Ollama, MLX, Groq, or any OpenAI-compatible endpoint. The CLI wires OLLAMA_BASE_URL so Docker can reach host Ollama." as const;

export const SPLIT_CARD_ENGINE = "Engine" as const;
export const SPLIT_CARD_WORKERS = "Workers" as const;

export const SPLIT_ENGINE_SUB = "Conductor brains" as const;
export const SPLIT_ENGINE_BODY =
  "eng-thinker · eng-verifier · eng-judge2 via Ollama — not in the Docker image, not selectable as workers." as const;

export const SPLIT_WORKERS_SUB = "Your pool (≤5)" as const;
export const SPLIT_WORKERS_BODY =
  "Connect providers in the dashboard. Secrets stay on your machine." as const;

/* -------------------------------------------------------------------------- */
/* Demo / install                                                              */
/* -------------------------------------------------------------------------- */

export const DEMO_LABEL = "Install" as const;
export const DEMO_H2 = "One CLI. Full stack." as const;

export const DEMO_INSTALL_FOLLOW =
  "then bare routism for interactive setup — Docker, Ollama, engine models, API + UI." as const;

/* -------------------------------------------------------------------------- */
/* Proof                                                                       */
/* -------------------------------------------------------------------------- */

export const PROOF_LABEL = "Why Routism" as const;
export const PROOF_H2 = "Built for agents, not demos" as const;
export const PROOF_DOCS_LEAD = "Docs:" as const;
export const PROOF_DOCS_OPENAI = "OpenAI compat" as const;
export const PROOF_DOCS_API = "API reference" as const;

/* -------------------------------------------------------------------------- */
/* Download                                                                    */
/* -------------------------------------------------------------------------- */

export const DOWNLOAD_LABEL = "Get Routism" as const;
export const DOWNLOAD_H1_LINES = ["Ready to host.", "Ready to run."] as const;
export const DOWNLOAD_BODY =
  "Clone the public MIT repo. Install the CLI. Conduct your models." as const;
export const DOWNLOAD_CTA_GITHUB = "Star & clone on GitHub" as const;
export const DOWNLOAD_COPY_SETUP = "Copy full setup" as const;
export const DOWNLOAD_AGENT_MODEL_LEAD = "Agent model id:" as const;
export const DOWNLOAD_ENV_LEAD = "env:" as const;

/* -------------------------------------------------------------------------- */
/* Footer                                                                      */
/* -------------------------------------------------------------------------- */

export const FOOTER_WORDMARK = "ROUTISM" as const;
export const FOOTER_DISCLAIMER =
  "Showcase site only — product dashboard runs after you install locally. Not a multi-tenant SaaS; no OAuth or Stripe required." as const;
export const FOOTER_LEGAL_LINE =
  "MIT licensed · self-hosted · not a multi-tenant SaaS" as const;
export const FOOTER_COL_PRODUCT = "Product" as const;
export const FOOTER_COL_SOURCE = "Source" as const;
export const FOOTER_COL_LICENSE = "License" as const;
export const FOOTER_COL_NOTE = "Note" as const;
export const FOOTER_LINK_GITHUB = "GitHub" as const;
export const FOOTER_LINK_API = "API docs" as const;
export const FOOTER_LINK_OPENAI = "OpenAI compat" as const;
export const FOOTER_LINK_MIT = "MIT" as const;

/* -------------------------------------------------------------------------- */
/* Paper stack (Plan / Execute / Merge faces)                                  */
/* -------------------------------------------------------------------------- */

export const PAPER_STACK_CARDS = [
  {
    title: "Plan",
    body: "Conductor breaks the task",
    accent: "lime" as const,
  },
  {
    title: "Execute",
    body: "Workers run in your pool",
    accent: "green" as const,
  },
  {
    title: "Merge",
    body: "One scored answer",
    accent: "signal" as const,
  },
] as const;

/* -------------------------------------------------------------------------- */
/* Weights list (capability rows — titles only; facts supply model/ports)      */
/* -------------------------------------------------------------------------- */

export const WEIGHTS_LABEL = "Capabilities" as const;

export const WEIGHTS_ROWS = [
  { title: "OpenAI-compatible API", detail: "Chat Completions endpoint" },
  { title: "Self-hosted Docker stack", detail: "Control plane on your machine" },
  { title: "No SaaS accounts", detail: "No OAuth or billing required" },
  { title: "Engine ≠ Workers", detail: "Ollama engine · BYOK pool" },
] as const;

/** Model capability row title prefix; append MODEL_ID from facts. */
export const WEIGHTS_MODEL_TITLE = "Model id" as const;

export function weightsModelRow(modelId: string = MODEL_ID): {
  title: string;
  detail: string;
} {
  return { title: WEIGHTS_MODEL_TITLE, detail: modelId };
}

/* -------------------------------------------------------------------------- */
/* Ecosystem posters (names only — no partner / certified claims)              */
/* -------------------------------------------------------------------------- */

export const ECOSYSTEM_LABEL = "Works with your stack" as const;

export const ECOSYSTEM_POSTERS = [
  "Hermes",
  "Cursor",
  "OpenAI SDKs",
  "Docker",
  "Continue",
] as const;

/* -------------------------------------------------------------------------- */
/* Variants marquee (static row MVP)                                           */
/* -------------------------------------------------------------------------- */

export const MARQUEE_CARDS = [
  { title: "Docker", sub: "compose stack", accent: "blue" as const },
  { title: "CLI", sub: INSTALL_COMMAND, accent: "pink" as const },
  { title: "Local", sub: "your machine", accent: "green" as const },
] as const;

/* -------------------------------------------------------------------------- */
/* Type split (ENGINE / WORKERS crop)                                          */
/* -------------------------------------------------------------------------- */

export const TYPE_SPLIT_LABELS = {
  left: "Conductor",
  right: "Pool",
} as const;

export const TYPE_SPLIT_GLYPHS = {
  engine: "ENGINE",
  workers: "WORKERS",
} as const;
