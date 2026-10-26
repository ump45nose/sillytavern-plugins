import test from "node:test";
import assert from "node:assert/strict";
import { build } from "esbuild";

const { outputFiles } = await build({
  entryPoints: [new URL("../src/host/context-limit.ts", import.meta.url).pathname],
  bundle: true,
  format: "esm",
  write: false,
});
const { trimContext, firstSentFloor } = await import(
  "data:text/javascript;base64," + Buffer.from(outputFiles[0].text).toString("base64")
);
const on = { enabled: true, limit: 3, quiet: false };

test("keeps the newest messages of a generation", () => {
  const chat = [1, 2, 3, 4, 5];
  trimContext(chat, on, "normal");
  assert.deepEqual(chat, [3, 4, 5]);
});

test("off, short chats and quiet generations are left alone unless asked", () => {
  for (const [setting, type] of [
    [{ ...on, enabled: false }, "normal"],
    [undefined, "normal"],
    [on, "quiet"],
  ]) {
    const chat = [1, 2, 3, 4];
    trimContext(chat, setting, type);
    assert.equal(chat.length, 4);
  }
  const quiet = [1, 2, 3, 4];
  trimContext(quiet, { ...on, quiet: true }, "quiet");
  assert.deepEqual(quiet, [2, 3, 4]);
});

test("the first sent floor skips hidden floors", () => {
  const floors = [{ id: 0 }, { id: 1 }, { id: 2, hidden: true }, { id: 3 }, { id: 4 }];
  assert.equal(firstSentFloor(floors, on), 1);
  assert.equal(firstSentFloor(floors, { ...on, limit: 4 }), -1);
  assert.equal(firstSentFloor(floors, { ...on, enabled: false }), -1);
});
