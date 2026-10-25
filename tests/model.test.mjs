import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { transform } from "esbuild";
const { code } = await transform(
  await readFile(new URL("../src/host/model.ts", import.meta.url), "utf8"),
  { loader: "ts", format: "esm" },
);
const { deepMerge, mergeBook, mergeEdits, sameData, setActivation, validateBook, validatePreset } = await import(
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

test("sameData agrees with JSON equality and only walks branches that were replaced", () => {
  const book = { name: "b", entries: { 0: { ...entry }, 1: { ...entry, uid: 1 } } };
  assert.equal(sameData(book, structuredClone(book)), true);
  const edited = { ...book, entries: { ...book.entries, 1: { ...book.entries[1], content: "x" } } };
  assert.equal(sameData(book, edited), false);
  const restored = { ...edited, entries: { ...edited.entries, 1: { ...edited.entries[1], content: "original" } } };
  assert.equal(sameData(book, restored), true, "an edit typed back to the original is clean");
  assert.equal(sameData({ a: [1, 2] }, { a: [2, 1] }), false);
  assert.equal(sameData({ a: undefined }, {}), true, "like JSON, an undefined field is absent");
  assert.equal(sameData({ a: null }, {}), false);
  // Shared references are trusted: a branch that is the same object is not inspected.
  let reads = 0;
  const shared = { get deep() { reads++; return 1; } };
  assert.equal(sameData({ shared, x: 1 }, { shared, x: 1 }), true);
  assert.equal(reads, 0);
});

test("deepMerge mirrors the server's card merge: objects merge, arrays and scalars replace", () => {
  const card = { name: "A", tags: ["a", "b"], extensions: { fav: false, world: "w", vendor: { keep: 1 } } };
  const merged = deepMerge(card, { tags: ["c"], extensions: { fav: true, vendor: { extra: 2 } } });
  assert.deepEqual(merged, {
    name: "A",
    tags: ["c"],
    extensions: { fav: true, world: "w", vendor: { keep: 1, extra: 2 } },
  });
  assert.deepEqual(card.extensions, { fav: false, world: "w", vendor: { keep: 1 } }, "inputs are untouched");
});
