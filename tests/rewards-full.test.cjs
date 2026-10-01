"use strict";
const test = require("node:test"),
  assert = require("node:assert/strict");
const fs = require("node:fs"),
  os = require("node:os"),
  path = require("node:path");
const full = require("../platforms/rewards/full.cjs");
const ok = (business = { task: "complete" }) => ({
  execution: "ok",
  reason: "fixture",
  business,
});
const manifest = (enabled) => ({ schema_version: 1, enabled });
test("manifest rejects absent empty duplicate unknown and extra fields", () => {
  for (const value of [
    undefined,
    {},
    manifest([]),
    manifest(["daily", "daily"]),
    manifest(["typo"]),
    { ...manifest(["daily"]), approve: true },
  ])
    assert.throws(() => full.manifest(value));
  assert.deepEqual(full.manifest(manifest(["mobile_search", "daily"])), [
    "daily",
    "mobile_search",
  ]);
});
test("stages run sequentially in source order with before and after evidence", async () => {
  const events = [];
  let active = 0;
  const task = (name) => async () => {
    assert.equal(++active, 1);
    events.push(name);
    await Promise.resolve();
    active--;
    return ok();
  };
  const out = await full.execute(
    manifest(["desktop_search", "daily", "extra"]),
    {
      daily: task("daily"),
      extra: task("extra"),
      desktop_search: task("search"),
    },
    { snapshot: task("snapshot") },
  );
  assert.deepEqual(events, [
    "snapshot",
    "daily",
    "extra",
    "search",
    "snapshot",
  ]);
  assert.equal(out.reason, "full_requested_capabilities_complete");
});
test("snapshot success cannot erase partial task or missing enabled capability", async () => {
  const out = await full.execute(
    manifest(["daily", "claim"]),
    { daily: async () => ok({ daily: "unknown" }) },
    { snapshot: async () => ok() },
  );
  assert.equal(out.business.daily, "unknown");
  assert.equal(out.business.claim, "unknown");
  assert.equal(out.execution, "failed");
  assert.equal(out.report.stages.claim.reason, "capability_binding_pending");
});
test("completed narrow manifest does not claim unrequested capabilities ran", async () => {
  const out = await full.execute(manifest(["daily"]), {
    daily: async () => ok({ daily: "complete" }),
  });
  assert.deepEqual(out.business, { daily: "complete" });
  assert.deepEqual(Object.keys(out.report.stages), ["daily"]);
});
test("intervention stops later mutation and preserves earlier confirmed business", async () => {
  let calls = 0;
  const out = await full.execute(
    manifest(["daily", "extra", "punchcards"]),
    {
      daily: async () => ok(),
      extra: async () => ({
        execution: "failed",
        reason: "human_required",
        business: { goal: "blocked" },
      }),
      punchcards: async () => {
        calls++;
        return ok();
      },
    },
    { snapshot: async () => ok() },
  );
  assert.equal(out.business.daily, "complete");
  assert.equal(out.business.punchcards, "blocked");
  assert.equal(calls, 0);
  assert.equal(out.report.snapshots.after.reason, "not_run_after_stop");
});
test("one ordinary stage failure does not erase later independent success", async () => {
  const out = await full.execute(manifest(["daily", "extra"]), {
    daily: async () => {
      throw Error("network");
    },
    extra: async () => ok({ social: "complete" }),
  });
  assert.equal(out.business.daily, "unknown");
  assert.equal(out.business.extra, "complete");
  assert.equal(out.execution, "failed");
});
test("arbitrary raw fields and malformed business never enter reports", () => {
  const secret = ok();
  secret.token = "synthetic";
  assert.equal(full.validateOutput(secret).token, undefined);
  for (const business of [null, [], {}, { daily: [] }])
    assert.throws(() => full.validateOutput({ ...ok(), business }));
});
test("progress is bounded typed output after every requested stage", async () => {
  const reports = [];
  await full.execute(
    manifest(["daily", "claim"]),
    { daily: async () => ok() },
    {
      onProgress: async (value) =>
        reports.push(JSON.parse(JSON.stringify(value))),
    },
  );
  assert.equal(reports.length, 2);
  assert.equal(Object.keys(reports[0].stages).length, 1);
  assert.equal(Object.keys(reports[1].stages).length, 2);
});
test("execution failure cannot claim full completion despite known narrow success", async () => {
  const out = await full.execute(manifest(["daily"]), {
    daily: async () => ({
      execution: "failed",
      reason: "readback_failed",
      business: { daily: "complete" },
    }),
  });
  assert.equal(out.execution, "failed");
  assert.equal(out.reason, "full_requested_capabilities_partial");
  assert.equal(out.business.daily, "complete");
});
test("snapshot failure cannot erase successful business readback", async () => {
  const out = await full.execute(
    manifest(["daily"]),
    { daily: async () => ok({ daily: "complete" }) },
    {
      snapshot: async () => {
        throw Error("read unavailable");
      },
    },
  );
  assert.equal(out.business.daily, "complete");
  assert.equal(out.report.snapshots.after.reason, "snapshot_unavailable");
});
test("timeout and busy in initial snapshot stop all later mutations", async () => {
  for (const execution of ["timeout", "busy"]) {
    let called = false;
    const out = await full.execute(
      manifest(["daily"]),
      {
        daily: async () => {
          called = true;
          return ok();
        },
      },
      {
        snapshot: async () => ({
          execution,
          reason: "fixture",
          business: { daily: "unknown" },
        }),
      },
    );
    assert.equal(called, false);
    assert.equal(out.execution, execution);
    assert.equal(out.business.daily, "blocked");
  }
});
test("stage deadline does not reset for later phases", async () => {
  let called = false;
  const out = await full.execute(
    manifest(["daily", "extra"]),
    {
      daily: async () => ({
        execution: "timeout",
        reason: "deadline_exceeded",
        business: { daily: "unknown" },
      }),
      extra: async () => {
        called = true;
        return ok();
      },
    },
    { snapshot: async () => ok() },
  );
  assert.equal(called, false);
  assert.equal(out.execution, "timeout");
  assert.equal(out.reason, "full_deadline_exceeded");
});
test("account restriction in snapshot stops all mutations", async () => {
  let called = false;
  const out = await full.execute(
    manifest(["daily"]),
    {
      daily: async () => {
        called = true;
        return ok();
      },
    },
    {
      snapshot: async () => ({
        execution: "failed",
        reason: "account_restricted",
        business: { daily: "unknown" },
      }),
    },
  );
  assert.equal(called, false);
  assert.equal(out.reason, "full_intervention_pending");
});
test("missing desktop state fails binding preflight before APP client access", () => {
  let called = false;
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "rewards-full-"));
  try {
    assert.throws(
      () =>
        full.createBindings({
          stateDir: dir,
          host: {
            appClient: () => {
              called = true;
            },
          },
        }),
      /desktop_session_unavailable/,
    );
    assert.equal(called, false);
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});
test("successful browser state handoff closes resources; failed stage cannot replace state", async () => {
  const common = require("../platforms/rewards/browser_common.cjs");
  const events = [],
    next = { cookies: [], origins: [] };
  const context = {
    newPage: async () => ({}),
    storageState: async () => next,
    close: async () => events.push("context"),
  };
  const chromium = {
    launch: async () => ({
      newContext: async () => context,
      close: async () => events.push("browser"),
    }),
  };
  let preserved = 0;
  const options = {
    onVerifiedState: async (value) => {
      assert.equal(value, next);
      preserved++;
    },
  };
  await common.withBrowser(chromium, {}, options, async () => ok());
  await common.withBrowser(chromium, {}, options, async () => ({
    execution: "failed",
    business: { daily: "unknown" },
  }));
  assert.equal(preserved, 1);
  assert.deepEqual(events, ["context", "browser", "context", "browser"]);
});
test("native bindings inherit refreshed desktop state without writing credentials", async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "rewards-full-"));
  const initial = { cookies: [], origins: [] },
    next = {
      cookies: [],
      origins: [{ origin: "https://rewards.bing.com", localStorage: [] }],
    };
  const daily = require("../platforms/rewards/activities.cjs"),
    snapshot = require("../platforms/rewards/snapshot.cjs");
  const savedDaily = daily.run,
    savedSnapshot = snapshot.run;
  try {
    const file = path.join(dir, "storage-state.json");
    fs.writeFileSync(file, JSON.stringify(initial));
    daily.run = async (_c, state, options) => {
      assert.deepEqual(state, initial);
      await options.onVerifiedState(next);
      return ok();
    };
    snapshot.run = async (_c, state) => {
      assert.equal(state, next);
      return ok();
    };
    const native = full.createBindings({ stateDir: dir });
    await native.bindings.daily();
    await native.snapshot();
    assert.deepEqual(JSON.parse(fs.readFileSync(file)), initial);
  } finally {
    daily.run = savedDaily;
    snapshot.run = savedSnapshot;
    fs.rmSync(dir, { recursive: true, force: true });
  }
});
