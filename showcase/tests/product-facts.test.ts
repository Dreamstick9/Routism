/**
 * Fact-check tests — import shipped modules only (no reimplemented strings).
 * Values must match root README.md / install.sh / docs.
 */
import { describe, it } from "node:test";
import assert from "node:assert/strict";
import {
  AGENT_ENV_SNIPPET,
  API_BASE_URL,
  API_V1_BASE,
  DASHBOARD_URL,
  ENGINE_VS_WORKERS,
  GITHUB_DOCS_API,
  GITHUB_DOCS_OPENAI,
  GITHUB_URL,
  INSTALL_COMMAND,
  INSTALL_SNIPPET,
  MODEL_ID,
  NO_ACCOUNTS_CLAIM,
  PRODUCT_ONE_LINER,
  PROOF_CARDS,
  SECTIONS,
  sectionHref,
  sectionIds,
} from "../lib/product-facts";
import {
  getScrollTargets,
  isValidSectionId,
} from "../lib/scroll-map";

describe("product-facts (README-aligned)", () => {
  it("GitHub URL points at public Dreamstick9/Routism", () => {
    assert.equal(GITHUB_URL, "https://github.com/Dreamstick9/Routism");
  });

  it("install command is ./install.sh", () => {
    assert.equal(INSTALL_COMMAND, "./install.sh");
  });

  it("install snippet clones, installs, and runs bare routism", () => {
    assert.match(INSTALL_SNIPPET, /git clone https:\/\/github\.com\/Dreamstick9\/Routism\.git/);
    assert.match(INSTALL_SNIPPET, /\.\/install\.sh/);
    assert.match(INSTALL_SNIPPET, /^routism$/m);
    assert.ok(INSTALL_SNIPPET.includes(INSTALL_COMMAND));
  });

  it("model id is routism-ultra", () => {
    assert.equal(MODEL_ID, "routism-ultra");
  });

  it("API and dashboard ports match product defaults", () => {
    assert.equal(API_BASE_URL, "http://localhost:8000");
    assert.equal(API_V1_BASE, "http://localhost:8000/v1");
    assert.equal(DASHBOARD_URL, "http://localhost:3000");
  });

  it("agent env matches README block", () => {
    assert.match(AGENT_ENV_SNIPPET, /OPENAI_BASE_URL="http:\/\/localhost:8000\/v1"/);
    assert.match(AGENT_ENV_SNIPPET, /OPENAI_API_KEY="rtm_…"/);
    assert.match(AGENT_ENV_SNIPPET, /model: routism-ultra/);
    assert.match(AGENT_ENV_SNIPPET, /300–600 seconds/);
  });

  it("docs URLs are GitHub blob main paths", () => {
    assert.equal(
      GITHUB_DOCS_API,
      "https://github.com/Dreamstick9/Routism/blob/main/docs/API.md",
    );
    assert.equal(
      GITHUB_DOCS_OPENAI,
      "https://github.com/Dreamstick9/Routism/blob/main/docs/OPENAI_COMPAT.md",
    );
  });

  it("no SaaS account / OAuth / billing requirement claim", () => {
    assert.match(NO_ACCOUNTS_CLAIM, /No accounts/i);
    assert.match(NO_ACCOUNTS_CLAIM, /OAuth/i);
    assert.match(NO_ACCOUNTS_CLAIM, /billing/i);
    assert.match(NO_ACCOUNTS_CLAIM, /MIT/i);
  });

  it("engine ≠ workers message is present", () => {
    assert.match(ENGINE_VS_WORKERS, /Docker runs Routism/i);
    assert.match(ENGINE_VS_WORKERS, /Ollama runs the engine/i);
  });

  it("one-liner matches README positioning", () => {
    assert.match(PRODUCT_ONE_LINER, /Self-hosted/i);
    assert.match(PRODUCT_ONE_LINER, /OpenAI-compatible/i);
  });

  it("proof cards reference shipped facts", () => {
    assert.ok(PROOF_CARDS.length >= 4);
    const bodies = PROOF_CARDS.map((c) => c.body).join(" ");
    assert.ok(bodies.includes(MODEL_ID));
    assert.ok(bodies.includes(API_V1_BASE));
    assert.ok(bodies.includes(NO_ACCOUNTS_CLAIM) || bodies.includes("No accounts"));
  });
});

describe("section map / scroll targets", () => {
  it("SECTIONS order is world → hook → split → demo → proof → download", () => {
    assert.deepEqual(sectionIds(), [
      "world",
      "hook",
      "split",
      "demo",
      "proof",
      "download",
    ]);
  });

  it("sectionHref prefixes hash", () => {
    for (const s of SECTIONS) {
      assert.equal(sectionHref(s.id), `#${s.id}`);
    }
  });

  it("getScrollTargets maps every section id", () => {
    const map = getScrollTargets();
    for (const id of sectionIds()) {
      assert.equal(map[id], `#${id}`);
      assert.equal(isValidSectionId(id), true);
    }
    assert.equal(isValidSectionId("nope"), false);
  });
});
