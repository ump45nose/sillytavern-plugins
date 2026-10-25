import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { transform } from "esbuild";
const { code } = await transform(await readFile(new URL("../src/host/rp.ts", import.meta.url), "utf8"), { loader: "ts", format: "esm" });
const { boundedPreference } = await import("data:text/javascript;base64," + Buffer.from(code).toString("base64"));

test("RP layout preferences constrain persisted invalid values", () => {
  assert.equal(boundedPreference(NaN, 88, 65, 94), 88);
  assert.equal(boundedPreference(Infinity, 19, 14, 26), 19);
  assert.equal(boundedPreference(-1, 91, 55, 100), 55);
  assert.equal(boundedPreference(500, 88, 65, 94), 94);
});
