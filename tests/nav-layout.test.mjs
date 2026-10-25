import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { transform } from "esbuild";

const { code } = await transform(await readFile(new URL("../src/ui/navLayout.ts", import.meta.url), "utf8"), {
  loader: "ts",
  format: "esm",
});
const { planSections } = await import("data:text/javascript;base64," + Buffer.from(code).toString("base64"));

const section = (id, open, body, head = 36) => ({ id, open, head, body });
// A 600px column with three 36px title rows leaves 492px of room; 45% of the column is 270px.
const plan = (sections, recent = []) => planSections(sections, 600, recent);

test("expanded sections that fit keep their natural height", () => {
  assert.deepEqual(
    plan([section("history", true, 120), section("outline", false, 900), section("floors", true, 300)]),
    {
      history: { state: "open", max: null },
      outline: { state: "closed", max: null },
      floors: { state: "open", max: null },
    },
  );
});

test("a single expanded section fills the room and scrolls inside", () => {
  const p = plan([section("history", false, 0), section("outline", false, 0), section("floors", true, 3000)]);
  assert.deepEqual(p.floors, { state: "open", max: 492 });
});

test("several long sections are held to 45% and the leftover room goes back to them in order", () => {
  const p = plan([section("history", true, 90), section("outline", false, 0), section("floors", true, 3000)]);
  assert.deepEqual(p.history, { state: "open", max: null });
  assert.deepEqual(p.floors, { state: "open", max: 492 - 90 });
  const both = planSections(
    [section("a", true, 250), section("b", true, 400), section("c", true, 300)],
    1200,
    [],
  );
  // Room 1092; held 250 + 400 + 300 fits naturally, so nothing is capped.
  assert.deepEqual(both.b, { state: "open", max: null });
  const tight = planSections(
    [section("a", true, 100), section("b", true, 500), section("c", true, 500)],
    1000,
    [],
  );
  // Room 892; held 100 + 450 + 450 = 1000 overflows, so the focus (none recent: the first open) fills it.
  assert.deepEqual(tight, {
    a: { state: "open", max: 892 },
    b: { state: "auto", max: null },
    c: { state: "auto", max: null },
  });
});

test("when held sections still overflow only the focus stays open and the rest fold to their title rows", () => {
  const sections = [
    section("history", true, 400),
    section("outline", true, 50),
    section("floors", true, 3000),
  ];
  assert.deepEqual(plan(sections, ["floors", "history"]), {
    history: { state: "auto", max: null },
    outline: { state: "auto", max: null },
    floors: { state: "open", max: 492 },
  });
  assert.equal(plan(sections, ["history", "floors"]).history.state, "open");
  // A recent id that is not expanded is skipped.
  assert.equal(plan(sections, ["missing", "outline"]).outline.state, "open");
});

test("closing the focus restores the auto-folded sections", () => {
  const sections = [
    section("history", true, 200),
    section("outline", false, 0),
    section("floors", true, 3000),
  ];
  assert.equal(plan(sections, ["floors"]).history.state, "open", "200 + 270 fits in 492");
  const long = [section("history", true, 400), section("outline", false, 0), section("floors", true, 3000)];
  assert.equal(plan(long, ["floors"]).history.state, "auto");
  const closed = long.map((s) => (s.id === "floors" ? { ...s, open: false } : s));
  assert.deepEqual(plan(closed, ["floors"]), {
    history: { state: "open", max: null },
    outline: { state: "closed", max: null },
    floors: { state: "closed", max: null },
  });
});

test("gaps count against the room and an unmeasured column constrains nothing", () => {
  const sections = [section("a", true, 263), section("b", true, 263)];
  // 600 - 72 leaves 528: a 2px gap still fits 526, a 3px gap overflows and folds to the focus.
  assert.equal(planSections(sections, 600, [], { gap: 2 }).a.max, null);
  assert.deepEqual(planSections(sections, 600, ["b"], { gap: 3 }), {
    a: { state: "auto", max: null },
    b: { state: "open", max: 525 },
  });
  assert.deepEqual(planSections(sections, 0, []).b, { state: "open", max: null });
});
