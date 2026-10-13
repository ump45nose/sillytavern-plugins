import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { transform } from "esbuild";
const { code } = await transform(
  await readFile(new URL("../src/host/model.ts", import.meta.url), "utf8"),
  { loader: "ts", format: "esm" },
);
const { mergeBook, mergeEdits, setActivation, validateBook, validatePreset } = await import(
  "data:text/javascript;base64," + Buffer.from(code).toString("base64")
);
const entry = {
  uid: 0,
  content: "original",
  key: ["key"],
  disable: true,
  constant: false,
  vectorized: false,
  extension: { unknown: "keep" },
};
test("activation and enabled flags are independent and preserve extensions", () => {
  const vector = setActivation(entry, "vector");
  assert.equal(vector.disable, true);
  assert.equal(vector.vectorized, true);
  assert.equal(vector.constant, false);
  assert.deepEqual(vector.extension, entry.extension);
  const constant = setActivation(vector, "constant");
  assert.equal(constant.vectorized, false);
  assert.equal(constant.constant, true);
});
test("merge preserves concurrent untouched fields and refuses conflicting edits", () => {
  assert.deepEqual(
    mergeEdits(
      { name: "old", other: 1 },
      { name: "new", other: 1 },
      { name: "old", other: 2, unknown: 3 },
    ),
    { name: "new", other: 2, unknown: 3 },
  );
  assert.throws(
    () => mergeEdits({ name: "old" }, { name: "mine" }, { name: "theirs" }),
    /其他页面/,
  );
});
test("world roundtrip preserves unknown fields and independently changed entries", () => {
  const base = { entries: { 0: entry }, meta: { a: 1 } },
    draft = structuredClone(base),
    latest = structuredClone(base);
  draft.entries[0].content = "mine";
  latest.entries[0].extension.other = "external";
  latest.entries[1] = { ...entry, uid: 1 };
  const result = mergeBook(base, draft, latest);
  assert.equal(result.entries[0].content, "mine");
  assert.equal(result.entries[0].extension.other, "external");
  assert.deepEqual(result.entries[1], latest.entries[1]);
  assert.deepEqual(result.meta, { a: 1 });
});
test("world edits reject id collisions and concurrent deletion", () => {
  const base = { entries: { 0: entry } },
    draft = structuredClone(base);
  draft.entries[0].content = "edit";
  assert.throws(() => mergeBook(base, draft, { entries: {} }), /删除/);
  assert.throws(() => mergeBook({ entries: {} }, base, base), /冲突/);
});
test("invalid JSON world shape cannot be saved", () => {
  for (const bad of [
    { entries: null },
    { entries: [] },
    { entries: { 0: { ...entry, uid: 9 } } },
    { entries: { 0: { ...entry, key: "not array" } } },
  ])
    assert.throws(() => validateBook(bad));
});
test('JSON extension keys remain own properties without changing the object prototype',()=>{
 const draft=JSON.parse('{"__proto__":{"polluted":true}}');
 const result=mergeEdits({},draft,{});
 assert.equal(Object.getPrototypeOf(result),Object.prototype);
 assert.equal(Object.hasOwn(result,'__proto__'),true);
 assert.equal(result.polluted,undefined);
 assert.deepEqual(JSON.parse(JSON.stringify(result)),draft);
});


test("preset validation refuses malformed editable structures and preserves extension fields", () => {
  const preset = { prompts: [{ identifier: "test", content: "<xml>{{user}}</xml>", vendor: { keep: true } }], prompt_order: [{ character_id: 100000, order: [{identifier: "test", enabled: true}] }], unknown: { keep: true } };
  const before = JSON.stringify(preset);
  validatePreset(preset);
  assert.equal(JSON.stringify(preset), before);
  assert.throws(() => validatePreset({ prompts: {} }));
  assert.throws(() => validatePreset({ prompts: [{identifier:"x"},{identifier:"x"}] }));
  assert.throws(() => validatePreset({ prompt_order: [{order: [{}]}] }));
});
