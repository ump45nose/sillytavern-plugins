"use strict";
const test = require("node:test"), assert = require("node:assert/strict");
const fs = require("node:fs"), os = require("node:os"), path = require("node:path");
const app = require("../platforms/rewards/app.cjs");
function snapshot(current, max = 1) {
  return {execution: "ok", reason: "fixture", business: {app_daily: current === 1 ? "complete" : "incomplete"},
    details: {metrics: {app_daily: {unit: "count", current, max}}, items: []}};
}
function fixture(t) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "rewards-checkin-"));
  t.after(() => fs.rmSync(dir, {recursive: true, force: true}));
  let writes = 0;
  const client = {read: async () => ({}), submit: async () => { writes++; }};
  const saved = () => JSON.parse(fs.readFileSync(path.join(dir, "app-checkin-journal.json")));
  const run = (date, values) => app.submitDaily(client, app.checkinJournal(dir, date), date,
    {observeDaily: async () => values.length > 1 ? values.shift() : values[0], wait: async () => {}});
  return {dir, client, saved, run, writes: () => writes};
}
test("confirmed completion then two zero counters permits exactly one same-day cycle", async t => {
  const f = fixture(t), date = "2026-10-10";
  assert.equal((await f.run(date, [snapshot(1)])).business.app_daily, "complete");
  assert.equal((await f.run(date, [snapshot(0), snapshot(0), snapshot(1)])).business.app_daily, "complete");
  await f.run(date, [snapshot(1)]);
  assert.equal(f.writes(), 1);
  assert.equal(f.saved().generation, 1);
  assert.equal(f.saved().status, "confirmed");
  assert.equal(f.saved().previous.status, "confirmed");
});
test("one stale zero followed by complete does not replay the check-in", async t => {
  const f = fixture(t), date = "2026-10-10";
  await f.run(date, [snapshot(1)]);
  await f.run(date, [snapshot(0), snapshot(1)]);
  assert.equal(f.writes(), 0);
  assert.equal(f.saved().generation, 0);
});
test("missing and unrelated counters cannot release a confirmed cycle", async t => {
  const f = fixture(t), date = "2026-10-10";
  await f.run(date, [snapshot(1)]);
  for (const invalid of [snapshot(null), snapshot(0, 1000), {execution: "ok", business: {app_daily: "unknown"}}]) {
    const out = await f.run(date, [snapshot(0), invalid]);
    assert.equal(out.business.app_daily, "unknown");
    assert.equal(f.saved().status, "confirmed");
  }
  assert.equal(f.writes(), 0);
});
test("uncertain submission survives restart and midnight, then fresh completion reconciles it", async t => {
  const f = fixture(t);
  f.client.submit = async () => {
    assert.equal(f.saved().status, "attempted");
    throw Error("timeout");
  };
  await f.run("2026-10-10", [snapshot(0)]);
  f.client.submit = async () => assert.fail("uncertain request must not replay");
  for (const date of ["2026-10-10", "2026-10-11"])
    assert.equal((await f.run(date, [snapshot(0)])).reason, "previous_daily_submission_requires_reconciliation");
  assert.equal((await f.run("2026-10-11", [snapshot(1)])).business.app_daily, "complete");
  assert.equal(f.saved().status, "confirmed");
});
test("a reset cycle that is not credited is attempted once and stays uncertain", async t => {
  const f = fixture(t), date = "2026-10-10";
  await f.run(date, [snapshot(1)]);
  await f.run(date, [snapshot(0)]);
  await f.run(date, [snapshot(0)]);
  assert.equal(f.writes(), 1);
  assert.equal(f.saved().status, "attempted");
  assert.equal(f.saved().generation, 1);
});
test("authentication obstacles in reset readback stop without a write", async t => {
  const f = fixture(t), date = "2026-10-10";
  await f.run(date, [snapshot(1)]);
  const out = await f.run(date, [snapshot(0), {execution: "failed", reason: "human_required", business: {snapshot: "unknown"}}]);
  assert.equal(out.reason, "human_required");
  assert.equal(out.execution, "failed");
  assert.equal(f.writes(), 0);
});
test("rate-limited submission retains intent and has no retry", async t => {
  const f = fixture(t), date = "2026-10-10";
  f.client.submit = async () => { throw Error("app_rate_limited"); };
  await assert.rejects(f.run(date, [snapshot(0)]), /app_rate_limited/);
  assert.equal(f.saved().status, "attempted");
  f.client.submit = async () => assert.fail("must not replay");
  await f.run(date, [snapshot(0)]);
});
test("migration preserves old-day intent and leaves legacy journals byte-identical", async t => {
  const f = fixture(t);
  const old = JSON.stringify({schema_version: 1, business_date: "2026-10-10",
    entries: {"daily_2026-10-10": "attempted", "read_2026-10-10_0": "attempted"}});
  const promotions = JSON.stringify({"daily_2026-10-09": "confirmed", offer: "attempted"});
  fs.writeFileSync(path.join(f.dir, "app-daily-journal.json"), old);
  fs.writeFileSync(path.join(f.dir, "app-journal.json"), promotions);
  const out = await f.run("2026-10-11", [snapshot(0)]);
  assert.equal(out.reason, "previous_daily_submission_requires_reconciliation");
  assert.equal(f.writes(), 0);
  assert.equal(f.saved().status, "attempted");
  // Reading may rotate its legacy day file after check-in returns unknown.
  fs.writeFileSync(path.join(f.dir, "app-daily-journal.json"), JSON.stringify({
    schema_version: 1, business_date: "2026-10-11", entries: {}}));
  await f.run("2026-10-11", [snapshot(0)]);
  assert.equal(f.writes(), 0);
  fs.writeFileSync(path.join(f.dir, "app-daily-journal.json"), old);
  await f.run("2026-10-11", [snapshot(1)]);
  assert.equal(fs.readFileSync(path.join(f.dir, "app-daily-journal.json"), "utf8"), old);
  assert.equal(fs.readFileSync(path.join(f.dir, "app-journal.json"), "utf8"), promotions);
});
test("rolling cycle evidence stays bounded and rejects date regression and corrupt state", async t => {
  const f = fixture(t);
  await f.run("2026-10-10", [snapshot(1)]);
  for (let i = 0; i < 120; i++)
    await f.run("2026-10-11", [snapshot(0), snapshot(0), snapshot(1)]);
  assert.equal(f.writes(), 120);
  assert.ok(fs.statSync(path.join(f.dir, "app-checkin-journal.json")).size < 500);
  assert.throws(() => app.checkinJournal(f.dir, "2026-10-09"), /business_date_regressed/);
  for (const date of [undefined, "2026-02-30", "bad"])
    assert.throws(() => app.checkinJournal(f.dir, date), /business_date_invalid/);
  fs.writeFileSync(path.join(f.dir, "app-checkin-journal.json"), JSON.stringify({schema_version: 1}));
  assert.throws(() => app.checkinJournal(f.dir, "2026-10-11"), /journal_invalid/);
});
