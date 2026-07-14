/**
 * Single source of truth for showcase CTAs and product claims.
 * Must stay aligned with root README.md / install.sh / docs.
 * Unit tests import this module — do not duplicate strings in tests.
 */

export const GITHUB_URL = "https://github.com/Dreamstick9/Routism" as const;

export const DOCS_API_PATH = "/docs/API.md" as const; // relative in monorepo; GitHub blob below

export const GITHUB_DOCS_API =
  "https://github.com/Dreamstick9/Routism/blob/main/docs/API.md" as const;

export const GITHUB_DOCS_OPENAI =
  "https://github.com/Dreamstick9/Routism/blob/main/docs/OPENAI_COMPAT.md" as const;

export const MODEL_ID = "routism-ultra" as const;

export const API_BASE_URL = "http://localhost:8000" as const;
export const API_V1_BASE = "http://localhost:8000/v1" as const;
export const DASHBOARD_URL = "http://localhost:3000" as const;

/** Primary install entry (README) */
export const INSTALL_COMMAND = "./install.sh" as const;

/** Multi-line setup snippet shown in terminal + copy */
export const INSTALL_SNIPPET = `git clone https://github.com/Dreamstick9/Routism.git Routism
cd Routism
./install.sh
routism` as const;

/** Agent env block (README) */
export const AGENT_ENV_SNIPPET = `export OPENAI_BASE_URL="http://localhost:8000/v1"
export OPENAI_API_KEY="rtm_…"
# model: routism-ultra
# Client timeout: 300–600 seconds` as const;

export const PRODUCT_ONE_LINER =
  "Self-hosted, OpenAI-compatible multi-model orchestration for coding agents." as const;

export const PRODUCT_HOOK =
  "Agents speak one model. We conduct many." as const;

export const ENGINE_VS_WORKERS =
  "Docker runs Routism. Ollama runs the engine. You bring the workers." as const;

export const NO_ACCOUNTS_CLAIM =
  "No accounts, OAuth, or billing — single installation, MIT licensed." as const;

/** Section anchors for nav + scroll (order = page order); ids locked for tests */
export const SECTIONS = [
  { id: "world", label: "Intro" },
  { id: "hook", label: "Story" },
  { id: "split", label: "Architecture" },
  { id: "demo", label: "Install" },
  { id: "proof", label: "Why" },
  { id: "download", label: "Get it" },
] as const;

export type SectionId = (typeof SECTIONS)[number]["id"];

export function sectionHref(id: SectionId | string): string {
  return `#${id}`;
}

/** Map used by scroll spy / nav — pure, testable */
export function sectionIds(): string[] {
  return SECTIONS.map((s) => s.id);
}

export const PROOF_CARDS = [
  {
    title: "OpenAI-compatible",
    body: `Point Hermes, Cursor, or any SDK at ${API_V1_BASE}. Model id: ${MODEL_ID}.`,
  },
  {
    title: "Self-hosted",
    body: "Your machine, your Docker stack. No cloud lock-in for the control plane.",
  },
  {
    title: "No SaaS accounts",
    body: NO_ACCOUNTS_CLAIM,
  },
  {
    title: "Engine ≠ Workers",
    body: ENGINE_VS_WORKERS,
  },
] as const;
