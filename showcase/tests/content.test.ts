/**
 * Presentational copy deck — structure only (no product-truth reimplementation).
 * Product claims remain asserted in product-facts.test.ts.
 */
import { describe, it } from "node:test";
import assert from "node:assert/strict";
import {
  CTA_GET_ROUTISM,
  ECOSYSTEM_POSTERS,
  FOOTER_WORDMARK,
  HERO_H1_LINES,
  HOOK_STACK_LINES,
  MARQUEE_CARDS,
  PAPER_STACK_CARDS,
  SPLIT_H2,
  TYPE_SPLIT_GLYPHS,
  TYPE_SPLIT_LABELS,
} from "../lib/content";
import { INSTALL_COMMAND } from "../lib/product-facts";

describe("content deck (presentational)", () => {
  it("hero H1 is two frozen lines", () => {
    assert.deepEqual([...HERO_H1_LINES], ["Conduct many models", "as one API"]);
  });

  it("hook stack is Plan / Execute / Merge", () => {
    assert.deepEqual([...HOOK_STACK_LINES], ["Plan.", "Execute.", "Merge."]);
  });

  it("architecture display heading is Engine ≠ Workers", () => {
    assert.equal(SPLIT_H2, "Engine ≠ Workers");
  });

  it("paper stack has three Plan/Execute/Merge cards", () => {
    assert.equal(PAPER_STACK_CARDS.length, 3);
    assert.deepEqual(
      PAPER_STACK_CARDS.map((c) => c.title),
      ["Plan", "Execute", "Merge"],
    );
  });

  it("ecosystem posters are names only (≥4)", () => {
    assert.ok(ECOSYSTEM_POSTERS.length >= 4);
  });

  it("type-split labels are Conductor / Pool; glyphs ENGINE / WORKERS", () => {
    assert.equal(TYPE_SPLIT_LABELS.left, "Conductor");
    assert.equal(TYPE_SPLIT_LABELS.right, "Pool");
    assert.equal(TYPE_SPLIT_GLYPHS.engine, "ENGINE");
    assert.equal(TYPE_SPLIT_GLYPHS.workers, "WORKERS");
  });

  it("footer wordmark is ROUTISM; primary CTA label frozen", () => {
    assert.equal(FOOTER_WORDMARK, "ROUTISM");
    assert.equal(CTA_GET_ROUTISM, "Get Routism");
  });

  it("marquee CLI card sub comes from product facts install command", () => {
    const cli = MARQUEE_CARDS.find((c) => c.title === "CLI");
    assert.ok(cli);
    assert.equal(cli.sub, INSTALL_COMMAND);
  });
});
