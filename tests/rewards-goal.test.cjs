"use strict";
const test = require("node:test"),
  assert = require("node:assert/strict");
const { destination, setManualGoal } = require("../platforms/rewards/goal.cjs");
const URL = "https://rewards.bing.com/redeem/sku/000800000000";
function fixture({
  existing = false,
  timeout = false,
  manualMissing = false,
} = {}) {
  let selected = existing,
    manual = false;
  const events = [];
  const control = {
    count: async () => 1,
    waitFor: async () => {},
    isChecked: async () => selected,
  };
  const radio = {
    count: async () => (manualMissing ? 0 : 1),
    check: async () => {
      manual = true;
      events.push("manual");
    },
    isChecked: async () => manual,
  };
  const dialog = {
    count: async () => 1,
    waitFor: async () => {},
    getByRole(role, { name }) {
      if (role === "radio") return radio;
      return {
        count: async () => 1,
        click: async () => {
          events.push(name);
          if (name === "Next") {
            assert.equal(manual, true);
            selected = true;
            if (timeout) throw Error("timeout");
          }
        },
      };
    },
    getByText: () => ({ waitFor: async () => {} }),
  };
  const page = {
    url: () => URL,
    goto: async () => {},
    reload: async () => {},
    getByRole: (role) => (role === "switch" ? control : dialog),
    locator: () => ({
      filter: () => ({
        count: async () => 1,
        click: async () => events.push("toggle"),
      }),
    }),
  };
  const journal = { has: () => false, mark: async (_, s) => events.push(s) };
  return { page, journal, events };
}
test("goal requires trusted exact-action authorizer before any changing click", async () => {
  const f = fixture();
  await assert.rejects(
    setManualGoal(f.page, {
      url: URL,
      guard: async () => {},
      journal: f.journal,
    }),
    /human_required/,
  );
  assert.deepEqual(f.events, []);
});
test("manual goal flow preserves exact radio and reconciles uncertain Next", async () => {
  const f = fixture({ timeout: true });
  const result = await setManualGoal(f.page, {
    url: URL,
    checkpoint: {},
    authorize: async () => null,
    guard: async () => {},
    journal: f.journal,
  });
  assert.equal(result.business.goal, "complete");
  assert.deepEqual(f.events, [
    "attempted",
    "toggle",
    "manual",
    "Next",
    "confirmed",
  ]);
});
test("existing goal performs no change and does not assume existing auto-redeem configuration", async () => {
  const f = fixture({ existing: true });
  const result = await setManualGoal(f.page, {
    url: URL,
    guard: async () => {},
    journal: f.journal,
  });
  assert.match(result.reason, /mode_unchanged/);
  assert.deepEqual(f.events, []);
});
test("missing manual choice does not click Next or auto-redeem", async () => {
  const f = fixture({ manualMissing: true });
  const result = await setManualGoal(f.page, {
    url: URL,
    checkpoint: {},
    authorize: async () => null,
    guard: async () => {},
    journal: f.journal,
  });
  assert.equal(result.business.goal, "unknown");
  assert.deepEqual(f.events, ["attempted", "toggle"]);
});
test("goal destinations reject query, wrong hosts and paths", () => {
  for (const url of [
    "https://evil.invalid/redeem/sku/x",
    URL + "?secret=x",
    "https://rewards.bing.com/redeem/order",
  ])
    assert.throws(() => destination(url));
});
