import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { transform } from "esbuild";
const { code } = await transform(
  await readFile(new URL("../src/host/organize.ts", import.meta.url), "utf8"),
  { loader: "ts", format: "esm" },
);
const { groupItems, listOrder, unarchived, groupName, withGroup, withArchived, withoutStale, organized } =
  await import("data:text/javascript;base64," + Buffer.from(code).toString("base64"));

const prefs = (extra = {}) => ({ left: true, bindings: {}, groups: {}, ...extra });
const item = (id, group = "", archived = false) => ({ id, name: id, group, archived });

test("groups sort by Chinese collation with ungrouped last, keeping item order", () => {
  const groups = groupItems([item("a"), item("b", "三国"), item("c", "LPL"), item("d", "三国"), item("e")]);
  assert.deepEqual(
    groups.map((g) => [g.name, g.items.map((x) => x.id)]),
    [
      ["三国", ["b", "d"]],
      ["LPL", ["c"]],
      ["", ["a", "e"]],
    ].sort((a, b) => Number(!a[0]) - Number(!b[0]) || a[0].localeCompare(b[0], "zh")),
  );
});

test("list order skips archived items and follows the groups", () => {
  const items = [item("a"), item("b", "G"), item("c", "G", true), item("d", "", true)];
  assert.deepEqual(unarchived(items).map((x) => x.id), ["a", "b"]);
  assert.deepEqual(listOrder(items).map((x) => x.id), ["b", "a"]);
});

test("only books and connection profiles are organized", () => {
  assert.equal(organized("world"), true);
  assert.equal(organized("connection"), true);
  assert.equal(organized("preset"), false);
});

test("group names are trimmed and may not take the ungrouped label", () => {
  assert.equal(groupName("  古代 "), "古代");
  assert.throws(() => groupName("未分组"));
});

test("books group by name in worldGroups, profiles by id in groups; empty group removes", () => {
  const base = prefs({ groups: { p1: "Claude" }, worldGroups: { A: "旧" } });
  assert.deepEqual(withGroup(base, "world", ["A", "B"], "新"), { worldGroups: { A: "新", B: "新" } });
  assert.deepEqual(withGroup(base, "world", ["A"], ""), { worldGroups: {} });
  assert.deepEqual(withGroup(base, "connection", ["p2"], "GPT"), { groups: { p1: "Claude", p2: "GPT" } });
  assert.deepEqual(withGroup(prefs(), "world", ["A"], "X"), { worldGroups: { A: "X" } });
  // The input preferences are not mutated.
  assert.deepEqual(base.worldGroups, { A: "旧" });
});

test("archiving adds and restores without duplicates and keeps the other kind", () => {
  const base = prefs({ archived: { connection: ["p1"], world: ["A"] } });
  assert.deepEqual(withArchived(base, "world", ["A", "B"], true), { archived: { connection: ["p1"], world: ["A", "B"] } });
  assert.deepEqual(withArchived(base, "world", ["A"], false), { archived: { connection: ["p1"], world: [] } });
  assert.deepEqual(withArchived(prefs(), "connection", ["p9"], true), { archived: { connection: ["p9"] } });
});

test("stale keys are dropped; a kind that is not loaded is left alone", () => {
  const base = prefs({
    groups: { p1: "A", gone: "B" },
    worldGroups: { 书一: "古代", 已删: "古代" },
    archived: { connection: ["gone"], world: ["书一", "已删"] },
  });
  assert.deepEqual(withoutStale(base, { world: ["书一"], connection: ["p1"] }), {
    groups: { p1: "A" },
    worldGroups: { 书一: "古代" },
    archived: { connection: [], world: ["书一"] },
  });
  assert.deepEqual(withoutStale(base, { world: undefined, connection: ["p1", "gone"] }), null);
  assert.equal(withoutStale(prefs({ worldGroups: { 书一: "古代" } }), { world: ["书一"], connection: [] }), null);
});
