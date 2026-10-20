const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const {
  parseProgress,
  allowedCard,
  run,
  loadState,
} = require("../platforms/rewards/activities.cjs");
test("missing counters never turn into zero completion", () => {
  for (const [a, b] of [
    [null, "3"],
    ["", "3"],
    ["0", null],
    ["0", "0"],
    ["NaN", "3"],
    ["-1", "3"],
  ])
    assert.equal(parseProgress(a, b), null);
  assert.deepEqual(parseProgress("0", "3"), { current: 0, max: 3 });
});
test("cards restricted to explicit HTTPS first-party hosts", () => {
  assert.ok(allowedCard("https://www.bing.com/search?q=fixture"));
  for (const u of [
    "http://www.bing.com",
    "https://www.bing.com.evil.invalid",
    "https://user@www.bing.com",
    "https://www.bing.com:444",
    "javascript:alert(1)",
  ])
    assert.equal(allowedCard(u), false);
});
function fixture({
  now = "3",
  max = "3",
  fail = false,
  clickFail = false,
  challenge = false,
  login = false,
  restricted = false,
  credit = true,
  attributed = true,
  readbackTimeout = false,
  quizDestination = false,
} = {}) {
  const destination = quizDestination ? "https://www.bing.com/search?filters=" + encodeURIComponent(
    'BTEPOKey:"REWARDSQUIZ_ENUS_fixture" BTROID:"daily_fixture"') : "https://www.bing.com/search?q=fixture";
  const state = {
    contextClosed: false,
    browserClosed: false,
    clicks: 0,
    visits: 0,
    popupClosed: false,
    launch: null,
  };
  const bar = {
    waitFor: async () => {},
    getAttribute: async (n) => (n === "aria-valuenow" ? now : max),
  };
  const link = {
    innerText: async () => "Card",
    click: async () => {
      state.clicks++;
      if (clickFail) throw Error("fixture");
      if (credit) now = max;
    },
  };
  const panel = {
    locator: () => ({
      evaluateAll: async () => [
        {
          title: "Card",
          text: "Card",
          href: destination,
        },
      ],
      filter: () => ({ first: () => link }),
    }),
  };
  const control = { getAttribute: async () => "true", locator: () => panel };
  const popup = {
    url: () => "https://www.bing.com/search?q=fixture",
    locator: () => ({ count: async () => 0 }),
    waitForLoadState: async () => {},
    waitForTimeout: async () => {},
    close: async () => {
      state.popupClosed = true;
    },
  };
  const page = {
    evaluate: async () => ({
      userInfo: { isRewardsUser: true },
      flyoutResult: {
        dailySetPromotions: {"10/13/2026": [{offerId: "daily_fixture", title: "Card",
          destinationUrl: destination, complete: attributed && now === max}]},
        userStatus: { isRewardsUser: true },
        userWarnings: restricted
          ? [{ name: "Fraud_UserWarning_BotScore_UX" }]
          : [],
      },
    }),
    close: async () => {},
    url: () =>
      login ? "https://login.live.com/" : "https://rewards.bing.com/dashboard",
    locator: (selector) => selector.includes("progressbar") ? bar : ({
      count: async () => (challenge && selector.includes("captcha") ? 1 : 0),
      evaluateAll: async () => challenge && selector.includes("iframe"),
    }),
    goto: async () => {
      state.visits++;
      if (fail) throw Error("fixture");
    },
    getByRole: (role) => (role === "progressbar" ? bar : control),
    waitForEvent: async () => popup,
    waitForLoadState: async () => {},
    waitForFunction: async () => {
      if (readbackTimeout && state.clicks) {
        const error = Error("private navigation details");
        error.name = "TimeoutError";
        throw error;
      }
    },
    waitForTimeout: async () => {},
  };
  const context = {
    newPage: async () => page,
    close: async () => {
      state.contextClosed = true;
    },
  };
  return {
    state,
    complete: () => {now = max;},
    chromium: {
      launch: async (opts) => {
        state.launch = opts;
        return {
          newContext: async () => context,
          close: async () => {
            state.browserClosed = true;
          },
        };
      },
    },
  };
}
test("already complete no click and all browser resources close", async () => {
  const f = fixture();
  const r = await run(f.chromium, { cookies: [], origins: [] });
  assert.equal(r.business.daily, "complete");
  assert.equal(f.state.clicks, 0);
  assert.ok(f.state.contextClosed && f.state.browserClosed);
  assert.equal(f.state.launch.chromiumSandbox, true);
  assert.equal(f.state.launch.args, undefined);
});

test("daily native binding checks account warning before any card click", async () => {
  const f = fixture({ now: "0", max: "1", restricted: true });
  const out = await run(f.chromium, {});
  assert.equal(out.reason, "account_restricted");
  assert.equal(f.state.clicks, 0);
  assert.ok(f.state.contextClosed && f.state.browserClosed);
});
test("unknown before progress cannot submit", async () => {
  const f = fixture({ now: null });
  const r = await run(f.chromium, {});
  assert.equal(r.business.daily, "unknown");
  assert.equal(f.state.clicks, 0);
  assert.ok(f.state.browserClosed);
});
test("one click then readback confirms progress and closes popup", async () => {
  const f = fixture({ now: "0", max: "1" });
  const r = await run(f.chromium, {});
  assert.equal(r.business.daily, "complete");
  assert.equal(f.state.clicks, 1);
  assert.ok(f.state.popupClosed && f.state.browserClosed);
});
test("readback failure preserves the observed progress, offer intents and safe diagnostic", async () => {
  const f = fixture({now: "1", max: "3", credit: false, readbackTimeout: true});
  const out = await run(f.chromium, {});
  assert.equal(out.reason, "daily_browser_or_network_error");
  assert.equal(out.details.metrics.daily.current, 1);
  assert.equal(out.details.metrics.daily.max, 3);
  assert.equal(out.details.items[0].id, "daily_fixture");
  assert.equal(out.cycle, "2026-10-13");
  assert.equal(out.diagnostic.failure_class, "timeout");
  assert.ok(!JSON.stringify(out).includes("private navigation details"));
  assert.equal(f.state.clicks, 1);
});
test("unconfirmed daily click keeps intent and cannot be repeated on the same platform day", async () => {
  const f = fixture({now: "0", max: "1", credit: false}), entries = new Map();
  const options = {journalForCycle: date => {
    assert.equal(date, "2026-10-13");
    return {has: id => entries.has(id), mark: async (id, value) => entries.set(id, value)};
  }};
  const first = await run(f.chromium, {}, options);
  assert.equal(first.business.daily, "unknown");
  assert.equal(entries.get("daily_fixture"), "attempted");
  await run(f.chromium, {}, options);
  assert.equal(f.state.clicks, 1);
  f.complete();
  assert.equal((await run(f.chromium, {}, options)).business.daily, "complete");
  assert.equal(entries.get("daily_fixture"), "confirmed");
  assert.equal(f.state.clicks, 1);
});
test("an attempted quiz resumes at its destination without clicking its dashboard card again", async () => {
  const quiz = require("../platforms/rewards/daily_quiz.cjs"), original = quiz.finish;
  const f = fixture({now: "0", max: "1", credit: false, quizDestination: true});
  const entries = new Map([["daily_fixture", "attempted"]]);
  let resumed = 0;
  quiz.finish = async (_page, row, options) => {
    assert.equal(row.offerId, "daily_fixture");
    assert.equal(await options.confirmed(), false);
    f.complete();
    assert.equal(await options.confirmed(), true);
    resumed++;
  };
  try {
    const out = await run(f.chromium, {}, {journalForCycle: () => ({
      has: id => entries.has(id), mark: async (id, state) => entries.set(id, state),
    })});
    assert.equal(resumed, 1);
    assert.equal(f.state.clicks, 0);
    assert.equal(out.business.daily, "complete");
    assert.equal(entries.get("daily_fixture"), "confirmed");
  } finally {quiz.finish = original;}
});
test("an aggregate counter increase without this offer's completion cannot confirm the click", async () => {
  const f = fixture({now: "0", max: "1", attributed: false});
  const out = await run(f.chromium, {});
  assert.equal(out.business.daily, "unknown");
  assert.equal(out.details.items.find(row => row.id === "daily_fixture").status, "unknown");
});
test("click failure never retried and popup cleaned", async () => {
  const f = fixture({ now: "0", max: "1", clickFail: true });
  const r = await run(f.chromium, {});
  assert.equal(r.business.daily, "unknown");
  assert.equal(f.state.clicks, 1);
  assert.ok(
    f.state.popupClosed && f.state.contextClosed && f.state.browserClosed,
  );
});
test("page failure closes browser", async () => {
  const f = fixture({ fail: true });
  const r = await run(f.chromium, {});
  assert.equal(r.execution, "failed");
  assert.ok(f.state.browserClosed);
});
test("session lookup is read-only and selects exact account", () => {
  const { DatabaseSync } = require("node:sqlite");
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "benefits-fixture-"));
  const p = path.join(dir, "sessions.db");
  try {
    const db = new DatabaseSync(p);
    db.exec(
      "CREATE TABLE sessions(email TEXT,platform TEXT,storage_state TEXT)",
    );
    db.prepare("INSERT INTO sessions VALUES(?,?,?)").run(
      "fixture@example.invalid",
      "desktop",
      JSON.stringify({ cookies: [], origins: [] }),
    );
    db.close();
    assert.deepEqual(loadState(p, "fixture@example.invalid"), {
      cookies: [],
      origins: [],
    });
    assert.throws(() => loadState(p, "missing@example.invalid"));
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

test("daily activities stop on login or challenge without clicking", async () => {
  for (const options of [{ login: true }, { challenge: true }]) {
    const f = fixture({ ...options, now: "0", max: "1" });
    const out = await run(f.chromium, {});
    assert.equal(out.reason, "human_required");
    assert.equal(f.state.clicks, 0);
    assert.ok(f.state.contextClosed && f.state.browserClosed);
  }
});
