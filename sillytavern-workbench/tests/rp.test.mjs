import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { transform } from "esbuild";
const { code } = await transform(await readFile(new URL("../src/host/rp.ts", import.meta.url), "utf8"), { loader: "ts", format: "esm" });
const { dialoguePages, boundedPreference } = await import("data:text/javascript;base64," + Buffer.from(code).toString("base64"));

test("RP pages preserve block order and every native block exactly once", () => {
  const blocks = [{ length: 100 }, { length: 160 }, { length: 80 }, { length: 600 }, { length: 20 }];
  const pages = dialoguePages(blocks, 250);
  assert.deepEqual(pages, [[0], [1, 2], [3], [4]]);
  assert.deepEqual(pages.flat(), blocks.map((_, i) => i));
});
test("embedded content stays atomic; empty and very long content remain readable", () => {
  assert.deepEqual(dialoguePages([], 200), [[]]);
  assert.deepEqual(dialoguePages([{ length: 3000 }], 200), [[0]]);
  assert.deepEqual(dialoguePages([{ length: 5 }, { length: 1, atomic: true }, { length: 5 }], 200), [[0], [1], [2]]);
});
test("RP layout preferences constrain persisted invalid values", () => {
  assert.equal(boundedPreference(NaN, 88, 65, 94), 88);
  assert.equal(boundedPreference(Infinity, 19, 14, 26), 19);
  assert.equal(boundedPreference(-1, 91, 55, 100), 55);
  assert.equal(boundedPreference(500, 88, 65, 94), 94);
});
