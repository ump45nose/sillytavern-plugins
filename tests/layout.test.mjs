import test from "node:test";
import assert from "node:assert/strict";
import { build } from "esbuild";

const { outputFiles } = await build({
  entryPoints: [new URL("../src/ui/layout/model.ts", import.meta.url).pathname],
  bundle: true,
  format: "esm",
  write: false,
});
const m = await import("data:text/javascript;base64," + Buffer.from(outputFiles[0].text).toString("base64"));

const addons = { export: true, outline: true, "image-gen": true };
const env = (over = {}) => ({ mode: "novel", mobile: false, width: 1496, addons, database: true, ...over });
const sizes = { left: 260, right: 460, rail: 180 };
const still = { left: false, right: false };
const run = (state, ...actions) => actions.reduce(m.reduce, state);

test("initial left follows the preference only on novel desktop", () => {
  assert.equal(m.initial(env(), true).left, true);
  assert.equal(m.initial(env({ mode: "rp" }), true).left, false);
  assert.equal(m.initial(env({ mobile: true, width: 400 }), true).left, false);
});

test("opening a panel remembers it, reopens the rail and closes the chooser", () => {
  const s = run(
    m.initial(env(), true),
    { type: "chooser", chooser: "preset" },
    { type: "rail", open: false },
    { type: "panel", panel: "world", id: "灯塔" },
  );
  assert.equal(s.panel, "world");
  assert.equal(s.lastPanel, "world");
  assert.equal(s.focusId, "灯塔");
  assert.equal(s.railOpen, true);
  assert.equal(s.chooser, null);
  const closed = m.reduce(s, { type: "panel", panel: null });
  assert.equal(closed.panel, null);
  assert.equal(m.lastAvailablePanel(closed), "world");
});

test("the left sidebar gives way to a panel when the reading column would drop below 420px", () => {
  const wide = run(m.initial(env(), true), { type: "panel", panel: "trace" });
  // 1496 - 260 - 460 = 776 without the rail.
  assert.equal(m.leftVisible(wide, sizes), true);
  const narrow = run(m.initial(env({ width: 1300 }), true), { type: "panel", panel: "world" });
  // 1300 - 260 - 460 - 180 (rail) = 400.
  assert.equal(m.leftVisible(narrow, sizes), false);
  assert.equal(m.leftVisible(m.reduce(narrow, { type: "rail", open: false }), sizes), true);
});

test("toggle-left on a crowded sidebar closes the panel instead of flipping the preference", () => {
  const s = run(m.initial(env({ width: 1300 }), true), { type: "panel", panel: "world" });
  const next = m.reduce(s, { type: "toggle-left", hover: still, sizes });
  assert.equal(next.panel, null);
  assert.equal(next.left, true);
  assert.equal(m.reduce(next, { type: "toggle-left", hover: still, sizes }).left, false);
});

test("toggle-left pins a hover-revealed sidebar", () => {
  const s = m.initial(env(), false);
  const next = m.reduce(s, { type: "toggle-left", hover: { left: true, right: false }, sizes });
  assert.equal(next.left, true);
});

test("compact RP keeps one overlay at a time", () => {
  let s = m.initial(env({ mode: "rp", width: 1000 }), true);
  s = m.reduce(s, { type: "toggle-left", hover: still, sizes });
  assert.equal(s.left, true);
  s = m.reduce(s, { type: "panel", panel: "preset" });
  assert.equal(s.left, false);
  assert.equal(m.bodyClasses(s, still, sizes)["wb-rp-overlay-open"], true);
  assert.equal(m.reduce(s, { type: "image-input" }).panel, null);
  // Wide RP leaves both sidebars alone.
  const wide = run(m.initial(env({ mode: "rp" }), true), { type: "panel", panel: "preset" });
  assert.equal(m.reduce(wide, { type: "image-input" }).panel, "preset");
});

test("PWA drawers are exclusive", () => {
  let s = m.initial(env({ mobile: true, width: 400 }), true);
  s = m.reduce(s, { type: "toggle-left", hover: still, sizes });
  assert.equal(s.left, true);
  s = m.reduce(s, { type: "panel", panel: "character" });
  assert.equal(s.left, false);
  s = m.reduce(s, { type: "toggle-left", hover: still, sizes });
  assert.deepEqual([s.left, s.panel], [true, null]);
  s = m.reduce(s, { type: "help", open: true });
  assert.deepEqual([s.left, s.help], [false, true]);
});

test("switching mode resets everything; switching device keeps settings and editors", () => {
  const busy = run(
    m.initial(env(), true),
    { type: "panel", panel: "world" },
    { type: "focus" },
    { type: "deep", deep: "outline" },
  );
  const rp = m.reduce(busy, { type: "env", env: { mode: "rp" }, prefLeft: true });
  assert.deepEqual([rp.panel, rp.deep, rp.focus, rp.left], [null, null, false, false]);
  const settings = m.reduce(m.initial(env(), true), {
    type: "settings",
    workspace: { page: "user" },
  });
  const phone = m.reduce(settings, { type: "env", env: { mobile: true, width: 400 }, prefLeft: true });
  assert.deepEqual(phone.workspace, { page: "user" });
  assert.equal(phone.left, false);
  const back = m.reduce(phone, { type: "env", env: { mobile: false, width: 1496 }, prefLeft: true });
  assert.equal(back.left, true);
  // A resize alone changes nothing else.
  const resized = m.reduce(busy, { type: "env", env: { width: 1300 }, prefLeft: true });
  assert.equal(resized.deep, "outline");
});

test("switching an add-on off closes its panel and editor and forgets it", () => {
  let s = run(m.initial(env(), true), { type: "panel", panel: "outline" });
  s = m.reduce(s, { type: "env", env: { addons: { ...addons, outline: false } }, prefLeft: true });
  assert.equal(s.panel, null);
  assert.equal(m.lastAvailablePanel(s), "character");
  assert.equal(m.reduce(s, { type: "panel", panel: "outline" }).panel, null);
  assert.equal(m.reduce(s, { type: "deep", deep: "outline" }).deep, null);
});

test("the database panel exists only while the plug-in does, and keeps the resource rail", () => {
  assert.equal(m.reduce(m.initial(env({ database: false }), true), { type: "panel", panel: "database" }).panel, null);
  let s = run(m.initial(env(), true), { type: "panel", panel: "database" });
  assert.equal(s.panel, "database");
  assert.equal(m.railVisible(s, still), true);
  s = m.reduce(s, { type: "env", env: { database: false }, prefLeft: true });
  assert.equal(s.panel, null);
  assert.equal(m.lastAvailablePanel(s), "character");
});

test("settings close every other surface", () => {
  const s = run(
    m.initial(env(), true),
    { type: "panel", panel: "world" },
    { type: "toggle-popup", popup: { kind: "menu", anchor: 1 } },
    { type: "settings", workspace: { page: "generation" } },
  );
  assert.deepEqual([s.panel, s.popup, s.deep], [null, null, null]);
  assert.equal(m.reduce(s, { type: "close-settings" }).workspace, null);
});

test("toggle-popup closes the same popup and replaces a different one", () => {
  const menu = { kind: "menu", anchor: 1 };
  let s = m.reduce(m.initial(env(), true), { type: "toggle-popup", popup: menu });
  assert.equal(s.popup, menu);
  assert.equal(m.reduce(s, { type: "toggle-popup", popup: { kind: "menu", anchor: 1 } }).popup, null);
  const tools = { kind: "tools", anchor: 1 };
  assert.equal(m.reduce(s, { type: "toggle-popup", popup: tools }).popup, tools);
});

test("leave guards run only when the visible view changes", () => {
  const s = run(m.initial(env(), true), { type: "panel", panel: "world", id: "a" });
  const to = (a, shown = s.panel, from = s) => m.leaves(from, m.reduce(from, a), shown);
  assert.equal(to({ type: "panel", panel: "preset" }), true);
  assert.equal(to({ type: "panel", panel: null }), true);
  assert.equal(to({ type: "panel", panel: "world", id: "b" }), true);
  assert.equal(to({ type: "panel", panel: "world", id: "a" }), false);
  assert.equal(to({ type: "chooser", chooser: "preset" }), false);
  assert.equal(to({ type: "settings", workspace: { page: "user" } }), true);
  // Pinning the hover-revealed panel keeps the user where they are.
  const idle = m.initial(env(), true);
  assert.equal(to({ type: "panel", panel: "character" }, "character", idle), false);
  assert.equal(to({ type: "panel", panel: "character" }, null, idle), true);
  // Closing settings is guarded by the settings page itself.
  const settings = m.reduce(idle, { type: "settings", workspace: { page: "user" } });
  assert.equal(to({ type: "close-settings" }, null, settings), false);
});
