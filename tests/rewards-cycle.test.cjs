"use strict";
const test = require("node:test"), assert = require("node:assert/strict");
const fs = require("node:fs"), os = require("node:os"), path = require("node:path");
const cycle = require("../platforms/rewards/daily_cycle.cjs"), full = require("../platforms/rewards/full.cjs");
test("visible cards select the platform cycle independently of the host's next day", () => {
  const rows = title => [{title, destinationUrl: "https://www.bing.com/search?q=" + title}];
  const raw = {flyoutResult: {dailySetPromotions: {"10/12/2026": rows("today"), "10/13/2026": rows("tomorrow")}}};
  assert.equal(cycle.inventory(raw, [{title: "today", href: "https://www.bing.com/search?q=today"}]).date, "2026-10-12");
  assert.equal(cycle.inventory(raw, [{title: "tomorrow", href: "https://www.bing.com/search?q=tomorrow"}]).date, "2026-10-13");
  assert.throws(() => cycle.inventory(raw, [{title: "unrecognized", href: "https://www.bing.com/"}]), /daily_cycle_unavailable/);
  assert.ok(cycle.matches({title: "Today's\u200b task", destinationUrl: "https://www.bing.com/"},
    {title: "Today's task", href: "https://rewards.bing.com/dashboard"}));
});
test("a platform reset during full execution invalidates completion from the preceding cycle", async () => {
  let calls = 0;
  const out = await full.execute({schema_version: 1, enabled: ["daily"]}, {
    daily: async () => ({execution: "ok", reason: "daily_complete", business: {daily: "complete"}}),
  }, {snapshot: async () => ({execution: "ok", reason: "fresh_readonly_snapshot",
    cycle: ++calls === 1 ? "2026-10-12" : "2026-10-13", business: {daily: "complete"}})});
  assert.equal(out.execution, "failed");
  assert.equal(out.reason, "full_task_cycle_changed");
  assert.equal(out.business.daily, "unknown");
});
test("a reset detected by the daily stage stops later submissions immediately", async () => {
  let later = 0;
  const out = await full.execute({schema_version: 1, enabled: ["daily", "extra"]}, {
    daily: async () => ({execution: "failed", reason: "daily_cycle_changed", cycle: "2026-10-13", business: {daily: "unknown"}}),
    extra: async () => {later++;},
  }, {snapshot: async () => ({execution: "ok", reason: "fresh_readonly_snapshot", cycle: "2026-10-12", business: {daily: "incomplete"}})});
  assert.equal(later, 0);
  assert.equal(out.reason, "full_task_cycle_changed");
  assert.equal(out.business.extra, "blocked");
});
test("search and activity journals use the observed platform cycle, preserving existing day files", async t => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "rewards-cycle-"));
  t.after(() => fs.rmSync(dir, {recursive: true, force: true}));
  fs.writeFileSync(path.join(dir, "storage-state.json"), JSON.stringify({cookies: [], origins: []}));
  fs.writeFileSync(path.join(dir, "explore-2026-10-13.json"), '{"prior":"attempted"}');
  const modules = [require("../platforms/rewards/extra.cjs"), require("../platforms/rewards/search.cjs"), require("../platforms/rewards/promotions.cjs")];
  const originals = modules.map(module => module.run);
  try {
    modules[0].run = async (_c, _s, _p, options) => {await options.journal.mark("fixture", "attempted");};
    modules[1].run = async (_c, _s, _d, options) => {await options.journal.mark("query_" + "a".repeat(64), "attempted");};
    modules[2].run = async (_c, _s, _p, options) => {await options.journal.mark("fixture", "attempted");};
    const native = full.createBindings({chromium: {}, stateDir: dir, enabled: ["extra", "desktop_search", "more_promotions"],
      host: {businessDate: "2026-10-13", browserSnapshot: async () => ({execution: "ok", cycle: "2026-10-12", business: {daily: "complete"}})}});
    await native.snapshot();
    for (const binding of Object.values(native.bindings)) await binding();
    for (const name of ["explore-2026-10-12.json", "search-desktop-2026-10-12.json", "promotions-2026-10-12.json"])
      assert.ok(fs.existsSync(path.join(dir, name)), name);
    assert.equal(fs.readFileSync(path.join(dir, "explore-2026-10-13.json"), "utf8"), '{"prior":"attempted"}');
  } finally {modules.forEach((module, index) => {module.run = originals[index];});}
});
