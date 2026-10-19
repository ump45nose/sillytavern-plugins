"use strict";
const test = require("node:test"),
  assert = require("node:assert/strict");
const fs = require("node:fs"),
  os = require("node:os"),
  path = require("node:path");
const { spawnSync } = require("node:child_process");
const full = require("../platforms/rewards/full.cjs");
const ok = (business = { task: "complete" }) => ({
  execution: "ok",
  reason: "fixture",
  business,
});
const manifest = (enabled) => ({ schema_version: 1, enabled });
test("desktop weekly capability reads before/after credit and uses its own weekly journal", async () => {
  const weekly = require("../platforms/rewards/desktop_app.cjs"), saved = weekly.run;
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "rewards-weekly-full-"));
  const calls = []; let credited = false;
  fs.writeFileSync(path.join(dir, "storage-state.json"), JSON.stringify({cookies: [], origins: []}));
  try {
    weekly.run = async (_c, _s, _p, options) => {
      calls.push(options.readOnly);
      if (!options.readOnly) {
        const journal = options.journalForQuest("WW_pcparent_RewardsApp_weekly_Exclusive_Octw2_2026_punchcard");
        await journal.mark("weekly_offer", "confirmed");
        credited = true;
      }
      return {execution: "ok", reason: "desktop_app_weekly_complete",
        business: {desktop_app_weekly: credited ? "complete" : "incomplete"},
        details: {metrics: {desktop_app_weekly: require("../common/details.cjs").metric("points", credited ? 10 : 0, 70)}, items: []}};
    };
    const native = full.createBindings({chromium: {}, stateDir: dir, enabled: ["desktop_app_weekly"],
      host: {browserSnapshot: async () => ({...ok(), cycle: "2026-10-13", details: {metrics: {}, items: []}})}});
    try {
      const out = await full.execute(manifest(["desktop_app_weekly"]), native.bindings, {snapshot: native.snapshot});
      assert.deepEqual(calls, [true, false, true]);
      assert.equal(out.business.desktop_app_weekly, "complete");
      assert.equal(out.details.metrics.desktop_app_weekly.before, 0);
      assert.equal(out.details.metrics.desktop_app_weekly.after, 10);
      assert.equal(out.details.metrics.desktop_app_weekly.delta, 10);
      assert.equal(fs.readdirSync(dir).filter(name => /^desktop-app-weekly-.*\.json$/.test(name)).length, 1);
    } finally {await native.close();}
  } finally {
    weekly.run = saved;
    fs.rmSync(dir, {recursive: true, force: true});
  }
});
test("desktop weekly rotation stops subsequent searches", async () => {
  let searched = false;
  const out = await full.execute(manifest(["desktop_app_weekly", "desktop_search"]), {
    desktop_app_weekly: async () => ({execution: "failed", reason: "desktop_app_weekly_changed", business: {desktop_app_weekly: "unknown"}}),
    desktop_search: async () => {searched = true; return ok();},
  });
  assert.equal(searched, false);
  assert.equal(out.reason, "full_task_cycle_changed");
});
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
test("delivery preserves search obstacle details across the final snapshot", async () => {
  const diagnostic = {id: "desktop_search_submission", name: "desktop search",
    status: "unknown", reason: "search_navigation_timeout"};
  const out = await full.execute(manifest(["desktop_search"]), {
    desktop_search: async () => ({...ok({desktop_search: "incomplete"}),
      details: {metrics: {}, items: [diagnostic]}}),
  }, {snapshot: async () => ({...ok(), details: {metrics: {}, items: []}})});
  assert.deepEqual(out.details.items, [diagnostic]);
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
  assert.deepEqual(reports[0].business, {
    daily: "complete",
    claim: "unknown",
  });
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
          enabled: ["daily", "app_promotions"],
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
test("native bindings persist and inherit verified desktop state", async () => {
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
    const native = full.createBindings({
      chromium: {},
      stateDir: dir,
      enabled: ["daily"],
    });
    await native.bindings.daily();
    await native.snapshot();
    assert.deepEqual(JSON.parse(fs.readFileSync(file)), next);
  } finally {
    daily.run = savedDaily;
    snapshot.run = savedSnapshot;
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

test("APP-only trusted bindings need no browser state, Chromium, or parser", async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "rewards-full-"));
  const common = require("../platforms/rewards/browser_common.cjs"),
    parser = require("../platforms/rewards/parser_loader.cjs");
  const savedState = common.readState,
    savedDependency = common.dependency,
    savedParser = parser.loadParser;
  let reads = 0,
    clients = 0;
  try {
    const unexpected = () => {
      throw Error("unexpected_browser_dependency");
    };
    common.readState = common.dependency = parser.loadParser = unexpected;
    const native = full.createBindings({
      stateDir: dir,
      enabled: ["app_promotions"],
      host: {
        appClient: async () => {
          clients++;
          return {
            read: async () => {
              reads++;
              return {
                response: {
                  profile: { ruid: "fixture-account" },
                  balance: 100,
                  promotions: [
                    {
                      attributes: {
                        type: "sapphire",
                        offerid: "fixture_offer",
                        complete: "true",
                      },
                    },
                  ],
                },
              };
            },
            submit: async () => {
              throw Error("unexpected_submission");
            },
          };
        },
      },
    });
    assert.deepEqual(Object.keys(native.bindings), ["app_promotions"]);
    const out = await full.execute(
      manifest(["app_promotions"]),
      native.bindings,
      native,
    );
    assert.equal(out.execution, "ok");
    assert.equal(out.business.app_promotions, "complete");
    assert.equal(
      out.report.snapshots.before.reason,
      "browser_snapshot_not_required",
    );
    assert.equal(
      out.report.snapshots.after.reason,
      "browser_snapshot_not_required",
    );
    assert.equal(clients, 3);
    assert.equal(reads, 3);
  } finally {
    common.readState = savedState;
    common.dependency = savedDependency;
    parser.loadParser = savedParser;
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

test("APP authentication stops later APP mutations without any desktop dependency", async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "rewards-full-"));
  let calls = 0;
  try {
    const native = full.createBindings({
      stateDir: dir,
      enabled: ["app_daily", "app_promotions", "read_to_earn"],
      host: {
        businessDate: "2026-10-10",
        appClient: async () => {
          calls++;
          throw Error("app_token_missing");
        },
      },
    });
    const out = await full.execute(
      manifest(["app_daily", "app_promotions", "read_to_earn"]),
      native.bindings,
      native,
    );
    assert.equal(calls, 2);
    assert.equal(out.reason, "full_intervention_pending");
    assert.deepEqual(out.business, {
      app_daily: "unknown",
      app_promotions: "unknown",
      read_to_earn: "blocked",
    });
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

test("production APP authorization failures are shared across snapshots and stages", async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "rewards-full-auth-"));
  const auth = require("../platforms/rewards/app_auth.cjs"), saved = auth.create;
  let attempts = 0;
  try {
    auth.create = async () => { attempts++; throw Error("app_authorization_timeout"); };
    const native = full.createBindings({stateDir: dir, enabled: ["app_promotions"]});
    const out = await full.execute(manifest(["app_promotions"]), native.bindings, native);
    assert.equal(attempts, 1);
    assert.equal(out.execution, "failed");
    assert.equal(out.report.stages.app_promotions.reason, "app_authorization_timeout");
    assert.equal(out.business.app_promotions, "unknown");
    await native.close();
  } finally {
    auth.create = saved;
    fs.rmSync(dir, {recursive: true, force: true});
  }
});

test("a cached APP session that expires during full execution refreshes before the later APP stage", async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "rewards-app-expiry-"));
  const auth = require("../platforms/rewards/app_auth.cjs"), savedCreate = auth.create, savedNow = Date.now;
  let now = savedNow(), creations = 0, closes = 0;
  try {
    Date.now = () => now;
    auth.create = async () => {
      creations++;
      return {expiresAt: now + (creations === 1 ? 61000 : 86400000), close: async () => {closes++;},
        client: {read: async () => ({response: {profile: {ruid: "fixture"}, balance: 100,
          promotions: [{attributes: {type: "sapphire", offerid: "fixture_offer", complete: "true"}}]}}),
          submit: async () => assert.fail("completed offers must not be submitted")}};
    };
    const native = full.createBindings({stateDir: dir, enabled: ["app_promotions"],
      config: {interaction: {enabled: false}}});
    await native.snapshot();
    assert.equal(creations, 1);
    now += 90000;
    assert.equal((await native.bindings.app_promotions()).business.app_promotions, "complete");
    await native.snapshot();
    assert.equal(creations, 2);
    assert.equal(closes, 1);
    await native.close();
    assert.equal(closes, 2);
  } finally {auth.create = savedCreate; Date.now = savedNow; fs.rmSync(dir, {recursive: true, force: true});}
});

test("APP check-in uses its cycle journal, reading and promotions retain their journals", async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "rewards-full-"));
  const app = require("../platforms/rewards/app.cjs");
  const saved = Object.fromEntries(
    ["dailyJournal", "checkinJournal", "submitDaily", "readToEarn", "runPromotions"].map(
      (key) => [key, app[key]],
    ),
  );
  const dailyJournal = { fixture: true },
    client = {},
    calls = [];
  try {
    const checkinJournal = {checkin: true};
    app.checkinJournal = (stateDir, date) => {
      assert.equal(stateDir, dir);
      assert.equal(date, "2026-10-02");
      return checkinJournal;
    };
    app.dailyJournal = (stateDir, date) => {
      assert.equal(stateDir, dir);
      assert.equal(date, "2026-10-02");
      return dailyJournal;
    };
    for (const method of ["submitDaily", "readToEarn"])
      app[method] = async (value, journal, date) => {
        assert.equal(typeof value === "function" ? await value() : value, client);
        assert.equal(journal, method === "submitDaily" ? checkinJournal : dailyJournal);
        assert.equal(date, "2026-10-02");
        calls.push(method);
        return { business: { task: "complete" } };
      };
    app.runPromotions = async (value, journal) => {
      assert.equal(value, client);
      assert.notEqual(journal, dailyJournal);
      assert.equal(journal.has("uncertain_offer"), true);
      calls.push("runPromotions");
      return { business: { task: "complete" } };
    };
    await require("../platforms/rewards/punchcards.cjs")
      .journal(path.join(dir, "app-journal.json"))
      .mark("uncertain_offer", "attempted");
    const enabled = ["app_daily", "app_promotions", "read_to_earn"];
    const native = full.createBindings({
      stateDir: dir,
      enabled,
      host: { appClient: async () => client, businessDate: "2026-10-02" },
    });
    const out = await full.execute(manifest(enabled), native.bindings, native);
    assert.equal(out.execution, "ok");
    assert.deepEqual(calls, ["submitDaily", "runPromotions", "readToEarn"]);
  } finally {
    for (const [key, value] of Object.entries(saved)) {
      if (value === undefined) delete app[key];
      else app[key] = value;
    }
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

test("mobile-only requests preflight and snapshot only the mobile account", async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "rewards-full-"));
  const search = require("../platforms/rewards/search.cjs"),
    snapshot = require("../platforms/rewards/snapshot.cjs"),
    parser = require("../platforms/rewards/parser_loader.cjs");
  const savedSearch = search.run,
    savedSnapshot = snapshot.run,
    savedParser = parser.loadParser;
  const state = { cookies: [], origins: [] },
    events = [];
  const next = {
    cookies: [],
    origins: [{ origin: "https://www.bing.com", localStorage: [] }],
  };
  try {
    fs.writeFileSync(
      path.join(dir, "storage-state.mobile.json"),
      JSON.stringify(state),
    );
    parser.loadParser = () => {
      throw Error("unexpected_parser");
    };
    search.run = async (_browser, value, device, options) => {
      assert.equal(device, "mobile");
      assert.deepEqual(value, state);
      assert.equal(options.contextOptions.isMobile, true);
      assert.equal(options.region, "US");
      events.push("mobile_search");
      await options.onVerifiedState(next);
      return ok();
    };
    snapshot.run = async (_browser, value, options) => {
      assert.deepEqual(value, events.length ? next : state);
      assert.equal(options.contextOptions.isMobile, true);
      assert.equal(options.region, "US");
      return ok();
    };
    const native = full.createBindings({
      chromium: {},
      stateDir: dir,
      enabled: ["mobile_search"],
      config: { mobile: { isMobile: true }, region: "US" },
      host: {businessDate: "2026-10-09"},
    });
    const out = await full.execute(
      manifest(["mobile_search"]),
      native.bindings,
      native,
    );
    assert.equal(out.execution, "ok");
    assert.deepEqual(events, ["mobile_search"]);
    assert.equal(fs.existsSync(path.join(dir, "storage-state.json")), false);
  } finally {
    search.run = savedSearch;
    snapshot.run = savedSnapshot;
    parser.loadParser = savedParser;
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

test("all enabled browser states are checked before an APP factory or browser dependency", () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "rewards-full-"));
  const common = require("../platforms/rewards/browser_common.cjs");
  const saved = common.dependency;
  let called = false;
  try {
    fs.writeFileSync(
      path.join(dir, "storage-state.json"),
      JSON.stringify({ cookies: [], origins: [] }),
    );
    common.dependency = () => {
      called = true;
      throw Error("unexpected_dependency");
    };
    assert.throws(
      () =>
        full.createBindings({
          stateDir: dir,
          enabled: ["daily", "mobile_search", "app_promotions"],
          host: {
            appClient: async () => {
              called = true;
            },
          },
        }),
      /mobile_session_unavailable/,
    );
    assert.equal(called, false);
  } finally {
    common.dependency = saved;
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

function entryFixture(
  enabled,
  { setup = "", config, browserState = false, cli = false } = {},
) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "rewards-full-entry-"));
  try {
    fs.writeFileSync(
      path.join(dir, "capabilities.json"),
      JSON.stringify(manifest(enabled)),
    );
    fs.writeFileSync(
        path.join(dir, "native-config.json"),
        JSON.stringify({interaction: {enabled: false}, ...config}),
      );
    if (browserState)
      fs.writeFileSync(
        path.join(dir, "storage-state.json"),
        JSON.stringify({ cookies: [], origins: [] }),
      );
    const resultPath = path.join(dir, "adapter-result.json");
    const code = `
      "use strict";
      const assert = require("node:assert/strict");
      const fs = require("node:fs"), path = require("node:path");
      const common = require("./platforms/rewards/browser_common.cjs");
      const fixture = () => ({ execution: "ok", reason: "fixture", business: { task: "complete" } });
      ${setup}
      require("./platforms/rewards/full.cjs").main().catch((error) => {
        console.error(error); process.exitCode = 90;
      });
    `;
    const child = spawnSync(
      process.execPath,
      cli ? ["platforms/rewards/full.cjs"] : ["-e", code],
      {
        cwd: path.join(__dirname, ".."),
        timeout: 5000,
        encoding: "utf8",
        env: {
          ...process.env,
          REWARDS_ROOT: "",
          BENEFITS_STATE_DIR: dir,
          BENEFITS_RESULT_PATH: resultPath,
          BENEFITS_RUN_ID: "fixture-run",
          BENEFITS_PLATFORM: "rewards",
          BENEFITS_ACCOUNT: "fixture-account",
          BENEFITS_BUSINESS_DATE: "2026-10-02",
        },
      },
    );
    assert.equal(child.error, undefined, child.stderr);
    const result = JSON.parse(fs.readFileSync(resultPath));
    const reportPath = path.join(dir, "rewards-report.json");
    const report =
      fs.existsSync(reportPath) && fs.statSync(reportPath).isFile()
        ? JSON.parse(fs.readFileSync(reportPath))
        : undefined;
    return { child, result, report };
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
}

const browserFixture = `
  common.dependency = () => ({});
  require("./platforms/rewards/snapshot.cjs").run = async () => ({...fixture(), cycle: "2026-10-01"});
  require("./platforms/rewards/activities.cjs").run = async () => fixture();
  require("./platforms/rewards/search.cjs").run = async () => fixture();
  require("./platforms/rewards/parser_loader.cjs").loadParser = () => { throw Error("unexpected_parser"); };
`;

test("CLI APP-only requests ignore JSON client or authorization callbacks", () => {
  const { child, result, report } = entryFixture(
    ["app_daily", "app_promotions", "read_to_earn"],
    {
      cli: true,
      config: {
        host: { appClient: "untrusted-module", businessDate: "2026-10-02" },
        appClient: "untrusted-module",
        authorize: true,
      },
    },
  );
  assert.equal(child.status, 1, child.stderr);
  assert.equal(result.reason, "full_requested_capabilities_partial");
  assert.deepEqual(result.business, {
    app_daily: "unknown",
    app_promotions: "unknown",
    read_to_earn: "unknown",
  });
  assert.equal(report.stages.app_daily.reason, "app_checkin_progress_unavailable");
  for (const key of ["app_promotions", "read_to_earn"])
    assert.equal(report.stages[key].reason, "capability_failed");
  assert.equal(report.snapshots.before.reason, "browser_snapshot_not_required");
});

test("unimplemented-only CLI capability stays honestly pending without browser prerequisites", () => {
  const { child, result, report } = entryFixture(["visual_search"], { cli: true });
  assert.equal(child.status, 1, child.stderr);
  assert.deepEqual(result.business, { visual_search: "unknown" });
  assert.equal(report.stages.visual_search.reason, "capability_binding_pending");
});

test("CLI missing required browser session stays a preflight error", () => {
  for (const [capability, reason] of [
    ["daily", "desktop_session_unavailable"],
    ["mobile_search", "mobile_session_unavailable"],
  ]) {
    const { child, result, report } = entryFixture([capability, "app_daily"], {
      cli: true,
    });
    assert.equal(child.status, 1, child.stderr);
    assert.equal(result.reason, reason);
    assert.deepEqual(result.business, {
      [capability]: "unknown",
      app_daily: "unknown",
    });
    assert.equal(report, undefined);
  }
});

test("entry atomically publishes all enabled business after each completed stage before interruption", () => {
  const { child, result, report } = entryFixture(["daily", "desktop_search"], {
    browserState: true,
    setup:
      browserFixture +
      `
      require("./platforms/rewards/search.cjs").run = async () => {
        const progress = JSON.parse(fs.readFileSync(process.env.BENEFITS_RESULT_PATH));
        assert.equal(progress.schema_version, 1);
        assert.equal(progress.run_id, "fixture-run");
        assert.equal(progress.platform, "rewards");
        assert.equal(progress.account, "fixture-account");
        assert.equal(progress.business_date, "2026-10-02");
        assert.equal(progress.execution_status, "failed");
        assert.equal(progress.reason, "full_in_progress");
        assert.deepEqual(progress.business, { daily: "complete", desktop_search: "unknown" });
        assert.equal(fs.existsSync(process.env.BENEFITS_RESULT_PATH + ".tmp-" + process.pid), false);
        process.exit(17);
      };
    `,
  });
  assert.equal(child.status, 17, child.stderr);
  assert.equal(result.reason, "full_in_progress");
  assert.deepEqual(result.business, {
    daily: "complete",
    desktop_search: "unknown",
  });
  assert.deepEqual(Object.keys(report.stages), ["daily"]);
});

test("entry final result replaces in-progress failure and preserves normal completion", () => {
  const { child, result, report } = entryFixture(["daily", "desktop_search"], {
    browserState: true,
    setup: browserFixture,
  });
  assert.equal(child.status, 0, child.stderr);
  assert.equal(result.execution_status, "ok");
  assert.equal(result.reason, "full_requested_capabilities_complete");
  assert.deepEqual(result.business, {
    daily: "complete",
    desktop_search: "complete",
  });
  assert.deepEqual(Object.keys(report.stages), ["daily", "desktop_search"]);
});

test("entry report failures preserve confirmed business and stop subsequent stages", () => {
  for (const destination of ["rewards-report.json", "adapter-result.json"]) {
    const { child, result } = entryFixture(["daily", "desktop_search"], {
      browserState: true,
      setup:
        browserFixture +
        `
        const write = fs.writeFileSync;
        let blocked = false;
        fs.writeFileSync = (file, ...args) => {
          if (!blocked && path.basename(file).startsWith(${JSON.stringify(destination + ".tmp-")})) {
            blocked = true;
            throw Error("fixture_reporting_failure");
          }
          return write(file, ...args);
        };
        require("./platforms/rewards/search.cjs").run = async () => {
          process.exit(91);
        };
      `,
    });
    assert.equal(child.status, 1, child.stderr);
    assert.equal(result.execution_status, "failed");
    assert.equal(result.reason, "full_preflight_or_reporting_failed");
    assert.deepEqual(result.business, {
      daily: "complete",
      desktop_search: "unknown",
    });
  }
});

test("entry final report failure keeps the complete stage result", () => {
  const { child, result } = entryFixture(["daily"], {
    browserState: true,
    setup:
      browserFixture +
      `
      const rename = fs.renameSync;
      let reports = 0;
      fs.renameSync = (from, to) => {
        if (path.basename(to) === "rewards-report.json" && ++reports === 2) {
          fs.unlinkSync(from);
          throw Error("fixture_final_report_failure");
        }
        return rename(from, to);
      };
    `,
  });
  assert.equal(child.status, 1, child.stderr);
  assert.equal(result.reason, "full_preflight_or_reporting_failed");
  assert.deepEqual(result.business, { daily: "complete" });
});

test("trusted full APP daily binding preserves an uncertain submission across local midnight", async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "rewards-full-app-days-"));
  let submits = 0;
  const client = {
    read: async () => ({
      response: {
        profile: { ruid: "fixture-account" },
        balance: 100,
        promotions: [],
      },
    }),
    submit: async (kind) => {
      assert.equal(kind, "daily");
      submits++;
    },
  };
  try {
    for (const date of ["2026-10-02", "2026-10-02", "2026-10-03"]) {
      const native = full.createBindings({
        stateDir: dir,
        enabled: ["app_daily"],
        host: { appClient: async () => client, businessDate: date,
          browserSnapshot: async () => ({...ok({app_daily: "incomplete"}),
            details: {metrics: {app_daily: {unit: "count", current: 0, max: 1}}, items: []}}) },
      });
      const out = await full.execute(
        manifest(["app_daily"]),
        native.bindings,
        native,
      );
      assert.equal(out.execution, "ok");
      assert.equal(out.business.app_daily, "unknown");
    }
    assert.equal(submits, 1);
    const saved = JSON.parse(
      fs.readFileSync(path.join(dir, "app-checkin-journal.json")),
    );
    assert.equal(saved.status, "attempted");
    assert.equal(saved.generation, 0);
    assert.equal(fs.existsSync(path.join(dir, "app-journal.json")), false);
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

test("full snapshots persist completion and the regular binding handles reset after the initial snapshot", async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "rewards-full-reset-"));
  let complete = true, submits = 0, initialComplete = false;
  const client = {read: async () => ({}), submit: async () => {submits++; complete = true;}};
  const host = {appClient: async () => client, businessDate: "2026-10-10",
    browserSnapshot: async () => {
      const current = initialComplete || complete ? 1 : 0;
      initialComplete = false;
      return {...ok({app_daily: current ? "complete" : "incomplete"}),
        details: {metrics: {app_daily: {unit: "count", current, max: 1}}, items: []}};
    }};
  try {
    const run = async () => {
      const native = full.createBindings({stateDir: dir, enabled: ["app_daily"], host});
      return full.execute(manifest(["app_daily"]), native.bindings, native);
    };
    assert.equal((await run()).business.app_daily, "complete");
    assert.equal(submits, 0);
    assert.equal(JSON.parse(fs.readFileSync(path.join(dir, "app-checkin-journal.json"))).status, "confirmed");
    complete = false;
    initialComplete = true;
    assert.equal((await run()).reason, "full_requested_capabilities_complete");
    await run();
    assert.equal(submits, 1);
    const saved = JSON.parse(fs.readFileSync(path.join(dir, "app-checkin-journal.json")));
    assert.equal(saved.generation, 1);
    assert.equal(saved.status, "confirmed");
  } finally {
    fs.rmSync(dir, {recursive: true, force: true});
  }
});

test("binding API requires explicit enabled capabilities before any dependency or account access", () => {
  const common = require("../platforms/rewards/browser_common.cjs");
  const saved = { readState: common.readState, dependency: common.dependency };
  try {
    common.readState = common.dependency = () =>
      assert.fail("manifest must be checked first");
    assert.throws(
      () =>
        full.createBindings({
          stateDir: "/no-account-files-needed",
          host: { appClient: () => assert.fail("must not call client") },
        }),
      /capability_manifest_invalid/,
    );
  } finally {
    Object.assign(common, saved);
  }
});
