"use strict";
const test = require("node:test"), assert = require("node:assert/strict");
const full = require("../platforms/rewards/full.cjs");
const {metric} = require("../common/details.cjs");
const parent = "WW_pcparent_RewardsApp_weekly_Exclusive_Octw2_2026_punchcard";
const child = "WW_pcchild6_urlreward_Thursday_RewardsApp_weekly_Exclusive_Octw2_2026_punchcard";
function snapshot(points, complete, week = parent) {
  return {execution: "ok", reason: "fresh_readonly_snapshot",
    business: {desktop_app_weekly: complete ? "complete" : "incomplete"},
    details: {metrics: {desktop_app_weekly: metric("points", points, 70)}, items: [
      {id: "desktop_app_weekly_quest", name: "Weekly quest", status: "incomplete",
        reason: "weekly_progress", url: "https://rewards.bing.com/earn/quest/" + week},
      {id: child, name: "Thursday", status: complete ? "complete" : "incomplete", reason: "fresh_readback"},
    ]}};
}
async function run(after, stage, before = snapshot(30, false)) {
  let reads = 0, submissions = 0;
  const out = await full.execute({schema_version: 1, enabled: ["desktop_app_weekly"]}, {
    desktop_app_weekly: async () => {
      submissions++;
      return stage || {...snapshot(30, false), execution: "failed", reason: "desktop_app_weekly_unavailable",
        business: {desktop_app_weekly: "unknown"}};
    },
  }, {snapshot: async () => reads++ ? after : before});
  assert.equal(submissions, 1);
  return out;
}
test("final same-week child and point readback resolves a failed stage without replay", async () => {
  const out = await run(snapshot(40, true));
  assert.equal(out.execution, "ok");
  assert.equal(out.business.desktop_app_weekly, "complete");
  assert.equal(out.details.metrics.desktop_app_weekly.delta, 10);
  assert.equal(out.details.items.find(row => row.id === child).status, "complete");
  assert.equal(out.report.stages.desktop_app_weekly.reason, "desktop_app_confirmed_by_fresh_snapshot");
});
test("a final readback failure or unconfirmed credit retains the failed stage", async () => {
  for (const after of [snapshot(30, false), {...snapshot(40, true), execution: "failed"},
    {...snapshot(30, false), business: {desktop_app_weekly: "unknown"}}]) {
    const out = await run(after);
    assert.equal(out.execution, "failed");
    assert.equal(out.business.desktop_app_weekly, "unknown");
  }
});
test("a missing or different weekly identity cannot confirm the failed submission", async () => {
  const absent = snapshot(40, true); absent.details.items = [];
  assert.equal((await run(absent)).business.desktop_app_weekly, "unknown");
  const rotated = await run(snapshot(40, true, parent.replace("Octw2", "Octw3")));
  assert.equal(rotated.execution, "failed");
  assert.equal(rotated.reason, "full_task_cycle_changed");
  assert.equal(rotated.business.desktop_app_weekly, "unknown");
  const staleStage = snapshot(30, false, parent.replace("Octw2", "Octw1"));
  staleStage.execution = "failed";
  assert.equal((await run(snapshot(40, true), staleStage)).execution, "failed");
});
test("an intervention still prevents reconciliation and later reads", async () => {
  const stage = {...snapshot(30, false), execution: "failed", reason: "human_required",
    business: {desktop_app_weekly: "blocked"}};
  const out = await run(snapshot(40, true), stage);
  assert.equal(out.execution, "failed");
  assert.equal(out.business.desktop_app_weekly, "blocked");
  assert.equal(out.report.snapshots.after.reason, "not_run_after_stop");
});
