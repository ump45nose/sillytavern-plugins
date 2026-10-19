"use strict";
const test = require("node:test"), assert = require("node:assert/strict");
const streaks = require("../platforms/rewards/streaks.cjs");
const interaction = require("../platforms/rewards/interaction.cjs");
function fixture(pending = true) {
  let presses = 0, intent = false;
  const rows = () => ["bing", "dailyset", "bingapp"].map(partner => ({partner,
    isEnabled: true, activitiesCompleted: partner === "bing" && pending && !presses ? 0 : 1,
    activitiesTotal: 1, isCurrentDayCompleted: partner !== "bing" || !pending || presses > 0,
    completedDays: 1, totalDays: 7}));
  const page = {goto: async () => {}, waitForTimeout: async () => {}, waitForLoadState: async () => {},
    locator: () => ({waitFor: async () => {}, fill: async () => {}, press: async () => {
      assert.equal(intent, true); presses++;
    }})};
  const deps = {withBrowser: async (_c, _s, _o, work) => work({}, page),
    readFlyout: async () => ({userInfo: {isRewardsUser: true}, flyoutResult: {userStatus: {isRewardsUser: true,
      counters: {PCSearch: [{pointProgress: 200, pointProgressMax: 200}]}}}}),
    assertAccountAvailable: require("../platforms/rewards/browser_common.cjs").assertAccountAvailable,
    guard: async () => {}, recordObstacle: () => {}};
  const options = {readStreaks: async () => rows(), search: {queries: ["weather forecast today"]},
    pacing: interaction.create({enabled: false}), journal: {has: () => false, mark: async () => {intent = true;}}};
  return {deps, options, presses: () => presses};
}
test("a pending Bing streak gets one real search even when the points quota is already full", async () => {
  const f = fixture();
  const out = await streaks.run(null, {}, f.options, f.deps);
  assert.equal(f.presses(), 1);
  assert.equal(out.business.bing_streak, "complete");
  assert.equal(out.details.metrics.bing_streak.unit, "count");
});
test("completed streaks are read without another search", async () => {
  const f = fixture(false);
  const out = await streaks.run(null, {}, f.options, f.deps);
  assert.equal(f.presses(), 0);
  assert.deepEqual(out.business, {bing_streak: "complete", daily_set_streak: "complete", app_streak: "complete"});
});
test("missing streak data stays unknown, and disabled streaks are not required", () => {
  assert.equal(streaks.summary([]).business.bing_streak, "unknown");
  assert.equal(streaks.measure({isEnabled: false, activitiesCompleted: 0, activitiesTotal: 1}).status, "not_applicable");
  assert.equal(streaks.measure({isEnabled: true, activitiesCompleted: 1, activitiesTotal: 1, isCurrentDayCompleted: false}).status, "incomplete");
});
test("a failed streak read disposes the response and does not repeat the HTTP request", async () => {
  let calls = 0, disposed = 0;
  await assert.rejects(streaks.read({request: {get: async () => {
    calls++; return {status: () => 503, body: async () => Buffer.from("unavailable"), dispose: async () => {disposed++;}};
  }}}), /streak_progress_unavailable/);
  assert.equal(calls, 1); assert.equal(disposed, 1);
});
