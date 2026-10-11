const test = require("node:test"),
  assert = require("node:assert/strict");
const search = require("../platforms/rewards/search.cjs"),
  common = require("../platforms/rewards/browser_common.cjs");
function q(earned, max = 9) {
  return {
    desktop_search: {
      status:
        earned === null ? "unknown" : earned >= max ? "complete" : "incomplete",
      earned,
      max,
    },
    edge_search: { status: "not_applicable", earned: 0, max: 0 },
  };
}
function fixture(values, { pressFails = false } = {}) {
  let i = 0,
    presses = 0;
  const page = {
    locator: () => ({
      waitFor: async () => {},
      fill: async () => {},
      press: async () => {
        presses++;
        if (pressFails) throw Error("timeout");
      },
    }),
    waitForTimeout: async () => {},
    waitForLoadState: async () => {},
    goto: async () => {},
  };
  return {
    page,
    observe: async () => q(values[Math.min(i++, values.length - 1)]),
    deps: { guard: async () => {} },
    presses: () => presses,
  };
}
test("strict desktop/mobile/Edge quotas preserve missing as unknown", () => {
  assert.equal(
    search.quota([{ pointProgress: null, pointProgressMax: 10 }]).status,
    "unknown",
  );
  const raw = {
    userInfo: { isRewardsUser: true },
    flyoutResult: {
      userStatus: {
        isRewardsUser: true,
        counters: {
          PCSearch: [
            { name: "pc", pointProgress: 3, pointProgressMax: 3 },
            { name: "Edge", pointProgress: 0, pointProgressMax: 3 },
          ],
          MobileSearch: [{ pointProgress: 0, pointProgressMax: 3 }],
        },
      },
    },
  };
  assert.equal(search.quotas(raw, "desktop").desktop_search.status, "complete");
  assert.equal(search.quotas(raw, "desktop").edge_search.status, "incomplete");
  assert.equal(search.quotas(raw, "mobile").mobile_search.status, "incomplete");
});
test("topic clusters are sequential deduplicated queries, not browser concurrency", () =>
  assert.deepEqual(
    search.queryQueue(
      ["Weather", "weather", "Science"],
      { Weather: ["weather tomorrow", "Weather"] },
      true,
    ),
    ["Weather", "weather tomorrow", "Science"],
  ));
test("complete quota skips all search input", async () => {
  const f = fixture([9]);
  const out = await search.runSession(
    f.page,
    f.observe,
    "desktop",
    search.configuration({ delayMs: 0 }),
    ["q"],
    f.deps,
  );
  assert.equal(out.execution, "ok");
  assert.equal(f.presses(), 0);
});
test("new search receives delayed credit before next query", async () => {
  const f = fixture([0, 0, 9]);
  const out = await search.runSession(
    f.page,
    f.observe,
    "desktop",
    search.configuration({ delayMs: 0, readbackDelayMs: 0 }),
    ["q", "q2"],
    f.deps,
  );
  assert.equal(out.reason, "search_quota_confirmed");
  assert.equal(f.presses(), 1);
});
test("uncertain Enter reconciles success without replay", async () => {
  const f = fixture([0, 9], { pressFails: true });
  const out = await search.runSession(
    f.page,
    f.observe,
    "desktop",
    search.configuration({ delayMs: 0 }),
    ["q"],
    f.deps,
  );
  assert.equal(out.reason, "search_reconciled_after_timeout");
  assert.equal(f.presses(), 1);
});
test("uncertain Enter without confirmation never repeats", async () => {
  const f = fixture([0, 0], { pressFails: true });
  const out = await search.runSession(
    f.page,
    f.observe,
    "desktop",
    search.configuration({ delayMs: 0 }),
    ["q", "q2"],
    f.deps,
  );
  assert.equal(out.reason, "search_submission_uncertain");
  assert.equal(f.presses(), 1);
  assert.equal(out.details.items[0].reason, "search_browser_error");
});
test("a resumed search skips a previously uncertain query in the daily journal", async () => {
  const rows = new Set();
  const journal = {has: id => rows.has(id), mark: async id => rows.add(id)};
  const first = fixture([0, 0], {pressFails: true});
  await search.runSession(first.page, first.observe, "desktop",
    search.configuration({delayMs: 0}), ["q", "q2"], first.deps, journal);
  assert.equal(rows.size, 1);
  const resumed = fixture([0, 9]);
  const filled = [];
  const locator = resumed.page.locator;
  resumed.page.locator = () => ({...locator(), fill: async text => filled.push(text)});
  const out = await search.runSession(resumed.page, resumed.observe, "desktop",
    search.configuration({delayMs: 0, maxSearches: 1}), ["Q", "q2"], resumed.deps, journal);
  assert.equal(out.reason, "search_quota_confirmed");
  assert.deepEqual(filled, ["q2"]);
});
test("search journal separates devices and permits the same query on the next day", async () => {
  const fs = require("node:fs"), os = require("node:os"), path = require("node:path");
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "rewards-search-journal-"));
  try {
    const today = search.dailyJournal(dir, "desktop", "2026-10-09");
    await today.mark("query_fixture", "attempted");
    assert.equal(search.dailyJournal(dir, "desktop", "2026-10-09").has("query_fixture"), true);
    assert.equal(search.dailyJournal(dir, "mobile", "2026-10-09").has("query_fixture"), false);
    assert.equal(search.dailyJournal(dir, "desktop", "2026-10-10").has("query_fixture"), false);
    assert.throws(() => search.dailyJournal(dir, "desktop", "../invalid"));
  } finally {fs.rmSync(dir, {recursive: true, force: true});}
});
test("a CAPTCHA after submission remains an obstacle even with a full quota", async () => {
  const f = fixture([0, 9]);
  const obstacle = new Error("captcha");
  obstacle.details = {code: "captcha", kind: "captcha"};
  let guards = 0;
  f.deps.guard = async () => { if (++guards === 2) throw obstacle; };
  await assert.rejects(search.runSession(f.page, f.observe, "desktop",
    search.configuration({delayMs: 0}), ["q"], f.deps), error => error === obstacle);
  assert.equal(f.presses(), 1);
});
test("stagnation stops bounded work rather than completing", async () => {
  const f = fixture([0]);
  const out = await search.runSession(
    f.page,
    f.observe,
    "desktop",
    search.configuration({ delayMs: 0, readbackAttempts: 1, stagnantLimit: 2 }),
    ["q", "q2", "q3"],
    f.deps,
  );
  assert.equal(out.reason, "search_stagnant");
  assert.equal(f.presses(), 2);
});
test("regressing counter needs fresh reconciliation", async () => {
  const f = fixture([3, 0]);
  const out = await search.runSession(
    f.page,
    f.observe,
    "desktop",
    search.configuration({ delayMs: 0, readbackAttempts: 1 }),
    ["q"],
    f.deps,
  );
  assert.equal(out.reason, "quota_regressed_reprobe_required");
});
test("query exhaustion and missing inventory are not success", async () => {
  const f = fixture([0]);
  const out = await search.runSession(
    f.page,
    f.observe,
    "desktop",
    search.configuration({ delayMs: 0 }),
    [],
    f.deps,
  );
  assert.equal(out.reason, "query_inventory_exhausted");
});
test("mobile requires an explicit consistent device profile before launching", async () => {
  let launched = false;
  const out = await search.run(
    {
      launch: async () => {
        launched = true;
      },
    },
    {},
    "mobile",
  );
  assert.equal(out.reason, "mobile_device_profile_required");
  assert.equal(launched, false);
});
test("recording, permissions and TLS weakening cannot enter context options", () => {
  for (const options of [
    { ignoreHTTPSErrors: true },
    { permissions: ["geolocation"] },
    { recordVideoDir: "/tmp" },
  ])
    assert.throws(
      () => common.contextOptions(options),
      /context_option_unsupported/,
    );
});
test("source bot-profile restriction is retained without treating absent as zero", () => {
  const attributes = {
    rbs: "1",
    SerpBotScore_upd: "fixture",
    AdsBotScore_upd: "fixture",
  };
  const raw = {
    userInfo: { isRewardsUser: true, profile: { attributes } },
    flyoutResult: {
      userStatus: {
        isRewardsUser: true,
        counters: {
          PCSearch: [{ pointProgressMax: 90 }],
          ActivityAndQuiz: [{ pointProgressMax: 0 }],
          DailyPoint: [{ pointProgressMax: 90 }],
        },
      },
    },
  };
  assert.equal(search.restricted(raw), true);
  assert.throws(() => search.quotas(raw, "desktop"), /account_restricted/);
  delete raw.flyoutResult.userStatus.counters.ActivityAndQuiz;
  assert.equal(search.restricted(raw), false);
});
test("explicit configured region mismatch stops rather than changing proxy", () => {
  const raw = {
    userInfo: {
      isRewardsUser: true,
      profile: { attributes: { country: "US" } },
    },
    flyoutResult: {
      userStatus: { isRewardsUser: true, counters: { PCSearch: [] } },
    },
  };
  assert.throws(() => search.quotas(raw, "desktop", "GB"), /region_mismatch/);
});

test("native desktop and mobile bindings use the bounded built-in query pool by default", async () => {
  const pool = require("../platforms/rewards/vendor/rewards-parser/src/functions/search-queries.json");
  assert.ok(
    pool.length > 1000,
    "fixture must exercise the original oversized default",
  );
  for (const device of ["desktop", "mobile"]) {
    let presses = 0;
    const page = {
      goto: async () => {},
      waitForLoadState: async () => {},
      waitForTimeout: async () => {},
      locator: () => ({
        waitFor: async () => {},
        fill: async () => {},
        press: async () => {
          presses++;
        },
      }),
    };
    const deps = {
      withBrowser: async (_c, _s, _o, work) => work({}, page),
      guard: async () => {},
      readFlyout: async () => ({
        userInfo: { isRewardsUser: true },
        flyoutResult: {
          userStatus: {
            isRewardsUser: true,
            counters: {
              [device === "mobile" ? "MobileSearch" : "PCSearch"]: [
                { pointProgress: presses * 3, pointProgressMax: 3 },
              ],
            },
          },
        },
      }),
    };
    const out = await search.run(
      null,
      {},
      device,
      {
        search: { delayMs: 0 },
        contextOptions: { isMobile: device === "mobile", userAgent: "fixture" },
      },
      deps,
    );
    assert.equal(out.business[device + "_search"], "complete");
    assert.equal(presses, 1);
  }
});
