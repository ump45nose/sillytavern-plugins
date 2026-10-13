"use strict";
const test = require("node:test"),
  assert = require("node:assert/strict");
const { destination, setManualGoal } = require("../platforms/rewards/goal.cjs");
const URL = "https://rewards.bing.com/redeem/sku/000800000000";
function fixture({
  existing = false,
  timeout = false,
  manualMissing = false,
  labelMissing = false,
  nextMissing = false,
  creditOnNext = true,
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
        count: async () => (name === "Next" && nextMissing ? 0 : 1),
        click: async () => {
          events.push(name);
          if (name === "Next") {
            assert.equal(manual, true);
            selected = creditOnNext;
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
        count: async () => (labelMissing ? 0 : 1),
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
    "toggle",
    "manual",
    "attempted",
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
  assert.deepEqual(f.events, ["toggle"]);
});
test("goal destinations reject query, wrong hosts and paths", () => {
  for (const url of [
    "https://evil.invalid/redeem/sku/x",
    URL + "?secret=x",
    "https://rewards.bing.com/redeem/order",
  ])
    assert.throws(() => destination(url));
});
test("missing goal label cannot poison the journal before any changing click", async () => {
  const f = fixture({ labelMissing: true });
  await assert.rejects(
    setManualGoal(f.page, {
      url: URL,
      checkpoint: {},
      authorize: async () => null,
      guard: async () => {},
      journal: f.journal,
    }),
    /goal_control_ambiguous/,
  );
  assert.deepEqual(f.events, []);
});

test("pre-submit goal controls can be repaired without poisoning a persistent journal", async () => {
  const fs = require("node:fs"),
    os = require("node:os"),
    path = require("node:path");
  const { journal } = require("../platforms/rewards/punchcards.cjs");
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "rewards-goal-repair-"));
  try {
    for (const defect of ["manualMissing", "nextMissing"]) {
      const file = path.join(dir, defect + ".json");
      const broken = fixture({ [defect]: true });
      const options = {
        url: URL,
        checkpoint: {},
        authorize: async () => null,
        guard: async () => {},
        journal: journal(file),
      };
      const before = await setManualGoal(broken.page, options);
      assert.equal(before.business.goal, "unknown");
      assert.deepEqual(
        broken.events,
        defect === "manualMissing" ? ["toggle"] : ["toggle", "manual"],
      );
      assert.equal(fs.existsSync(file), false);
      const repaired = fixture();
      const after = await setManualGoal(repaired.page, {
        ...options,
        journal: journal(file),
      });
      assert.equal(after.business.goal, "complete");
      assert.deepEqual(repaired.events, ["toggle", "manual", "Next", "Okay"]);
      assert.equal(
        JSON.parse(fs.readFileSync(file))["goal_000800000000"],
        "confirmed",
      );
    }
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

test("uncertain Next with no confirmed setting keeps persistent intent and cannot replay", async () => {
  const fs = require("node:fs"),
    os = require("node:os"),
    path = require("node:path");
  const { journal } = require("../platforms/rewards/punchcards.cjs");
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "rewards-goal-timeout-"));
  try {
    const file = path.join(dir, "goal.json");
    const first = fixture({ timeout: true, creditOnNext: false });
    const options = {
      url: URL,
      checkpoint: {},
      authorize: async () => null,
      guard: async () => {},
      journal: journal(file),
    };
    const out = await setManualGoal(first.page, options);
    assert.equal(out.business.goal, "unknown");
    assert.deepEqual(first.events, ["toggle", "manual", "Next"]);
    assert.equal(
      JSON.parse(fs.readFileSync(file))["goal_000800000000"],
      "attempted",
    );
    const second = fixture();
    const retry = await setManualGoal(second.page, {
      ...options,
      journal: journal(file),
    });
    assert.equal(retry.reason, "goal_previous_action_requires_reconciliation");
    assert.deepEqual(second.events, []);
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});
