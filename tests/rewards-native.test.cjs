const test = require("node:test"),
  assert = require("node:assert/strict"),
  fs = require("node:fs"),
  os = require("node:os"),
  path = require("node:path");
const snapshot = require("../platforms/rewards/snapshot.cjs"),
  extra = require("../platforms/rewards/extra.cjs"),
  common = require("../platforms/rewards/browser_common.cjs");
test("fresh snapshot null/zero/unknown counters fail closed", () => {
  assert.equal(snapshot.counter(null, null), "unknown");
  assert.equal(snapshot.counter(0, 0), "unknown");
  assert.equal(snapshot.counter(10, 10), "complete");
  assert.equal(
    snapshot.group([
      {
        pointProgress: 0,
        pointProgressMax: 10,
        exclusiveLockedFeatureStatus: null,
      },
    ]),
    "unknown",
  );
  assert.equal(snapshot.group([]), "not_applicable");
  assert.equal(snapshot.group(undefined), "unknown");
});
test("snapshot requires authenticated source", () =>
  assert.throws(() =>
    snapshot.summarize({ userInfo: { isRewardsUser: true } }, null),
  ));
test("snapshot reports bounded categories without account data", () => {
  const raw = {
    userInfo: { isRewardsUser: true },
    flyoutResult: {
      userStatus: {
        isRewardsUser: true,
        counters: {
          PCSearch: [{ pointProgress: 10, pointProgressMax: 10 }],
          MobileSearch: [],
        },
      },
      exploreOnBingPromotions: [],
      morePromotions: [{ complete: true }],
    },
  };
  assert.deepEqual(snapshot.summarize(raw, { current: 3, max: 3 }), {
    daily: "complete",
    desktop_search: "complete",
    mobile_search: "not_applicable",
    explore: "not_applicable",
    promotions: "complete",
  });
});
test("extras require explicit unlocked eligibility", () => {
  const offers = [
    {
      offerId: "SocialMediaFixture",
      title: "Example",
      isCompleted: false,
      isLocked: false,
    },
  ];
  assert.equal(extra.plan(offers, [])[0].status, "unknown");
  assert.equal(
    extra.plan(offers, [
      {
        offerId: "SocialMediaFixture",
        exclusiveLockedFeatureStatus: "unlocked",
      },
    ])[0].status,
    "eligible",
  );
  assert.equal(
    extra.plan(
      [{ offerId: "10XMSRewards_a30081646", isCompleted: false }],
      [],
    )[0].kind,
    "goal",
  );
});
test("extra destinations reject HTTP credentials and deceptive hosts", () => {
  assert.ok(
    extra.allowed("https://www.bing.com/search?q=test", ["www.bing.com"]),
  );
  for (const url of [
    "http://www.bing.com/",
    "https://www.bing.com.evil.test/",
    "https://x@www.bing.com/",
  ])
    assert.equal(extra.allowed(url, ["www.bing.com"]), false);
});
test("input reader caps bytes and validates storage state", () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "benefits-state-test-"));
  try {
    fs.writeFileSync(
      path.join(dir, "storage-state.json"),
      JSON.stringify({ cookies: [], origins: [] }),
    );
    assert.deepEqual(common.readState(dir), { cookies: [], origins: [] });
    fs.writeFileSync(
      path.join(dir, "storage-state.json"),
      "x".repeat(1024 * 1024 + 1),
    );
    assert.throws(() => common.readState(dir), /input_too_large/);
  } finally {
    fs.rmSync(dir, { recursive: true });
  }
});
test("guard never clicks login or challenge", async () => {
  await assert.rejects(
    () =>
      common.guard({
        url: () => "https://login.live.com/",
        locator: () => ({ count: async () => 0 }),
      }),
    /human_required/,
  );
  await assert.rejects(
    () =>
      common.guard({
        url: () => "https://rewards.bing.com/dashboard",
        locator: (selector) => ({
          count: async () => (selector.includes("captcha") ? 1 : 0),
        }),
      }),
    /human_required/,
  );
});
test("browser cleanup remains complete on thrown work", async () => {
  const called = [];
  const context = {
    newPage: async () => ({}),
    close: async () => called.push("context"),
  };
  const chromium = {
    launch: async (options) => {
      assert.equal(options.chromiumSandbox, true);
      return {
        newContext: async () => context,
        close: async () => called.push("browser"),
      };
    },
  };
  await assert.rejects(
    () =>
      common.withBrowser(chromium, {}, {}, async () => {
        throw Error("fixture");
      }),
    /fixture/,
  );
  assert.deepEqual(called, ["context", "browser"]);
});
function fakeExtra({
  goal = false,
  unknown = false,
  challenge = false,
  clickFails = false,
  restricted = false,
} = {}) {
  const id = goal ? "10XMSRewards_a30081646" : "SocialMediaFixture",
    events = [];
  let clicked = false;
  const target = {
    waitForLoadState: async () => {},
    waitForTimeout: async () => {},
    url: () => "https://www.youtube.com/watch?v=fixture",
    close: async () => events.push("popupClosed"),
  };
  const link = {
    first() {
      return this;
    },
    getAttribute: async () => "https://www.youtube.com/watch?v=fixture",
    click: async () => {
      events.push("click");
      if (clickFails) throw Error("timeout");
      clicked = true;
    },
  };
  const page = {
    goto: async () => {},
    waitForTimeout: async () => {},
    url: () => "https://rewards.bing.com/earn",
    locator: (selector) =>
      selector === "main"
        ? { waitFor: async () => {} }
        : { filter: () => link },
    waitForEvent: async () => target,
  };
  const deps = {
    EARN: common.EARN,
    withBrowser: async (chromium, state, opts, fn) => {
      try {
        return await fn({ newPage: async () => page }, page);
      } finally {
        events.push("contextClosed");
      }
    },
    guard: async () => {
      if (challenge) throw new common.HumanRequired();
    },
    boundedHtml: async () => "<fixture>",
    readFlyout: async () => ({
      userInfo: { isRewardsUser: true },
      flyoutResult: {
        userStatus: { isRewardsUser: true },
        userWarnings: restricted
          ? [{ name: "Fraud_UserWarning_BotScore_UX" }]
          : [],
        morePromotions: unknown
          ? []
          : [{ offerId: id, exclusiveLockedFeatureStatus: "unlocked" }],
        exploreOnBingPromotions: [],
      },
    }),
  };
  const parser = {
    snapshotPage: () => ({
      offers: [
        {
          offerId: id,
          title: "Fixture",
          isCompleted: clicked,
          isLocked: false,
        },
      ],
    }),
  };
  return { events, deps, parser };
}
test("extra social flow clicks once, reads back, closes popup", async () => {
  const f = fakeExtra();
  const out = await extra.run(null, {}, f.parser, {}, f.deps);
  assert.equal(out.business.social, "complete");
  assert.equal(f.events.filter((x) => x === "click").length, 1);
  assert.ok(f.events.includes("popupClosed"));
  assert.ok(f.events.includes("contextClosed"));
});
test("extra goal is blocked without any click", async () => {
  const f = fakeExtra({ goal: true });
  const out = await extra.run(null, {}, f.parser, {}, f.deps);
  assert.equal(out.business.goal, "blocked");
  assert.equal(out.reason, "goal_requires_manual_action");
  assert.ok(!f.events.includes("click"));
});
test("unknown extra eligibility never submits", async () => {
  const f = fakeExtra({ unknown: true });
  const out = await extra.run(null, {}, f.parser, {}, f.deps);
  assert.equal(out.business.social, "unknown");
  assert.ok(!f.events.includes("click"));
});
test("extra challenge halts and still cleans context", async () => {
  const f = fakeExtra({ challenge: true });
  const out = await extra.run(null, {}, f.parser, {}, f.deps);
  assert.equal(out.reason, "human_required");
  assert.ok(f.events.includes("contextClosed"));
  assert.ok(!f.events.includes("click"));
});
test("uncertain social click is not replayed", async () => {
  const f = fakeExtra({ clickFails: true });
  const out = await extra.run(null, {}, f.parser, {}, f.deps);
  assert.equal(out.business.social, "unknown");
  assert.equal(f.events.filter((x) => x === "click").length, 1);
  assert.ok(f.events.includes("popupClosed"));
});
test("duplicate or conflicting inventory cannot authorize action", () => {
  const offer = {
    offerId: "SocialMediaFixture",
    isCompleted: false,
    isLocked: false,
  };
  assert.throws(
    () => extra.plan([offer, offer], []),
    /duplicate_offer_inventory/,
  );
  assert.equal(
    extra.plan(
      [offer],
      [
        { offerId: offer.offerId, exclusiveLockedFeatureStatus: "locked" },
        { offerId: offer.offerId, exclusiveLockedFeatureStatus: "unlocked" },
      ],
    )[0].status,
    "unknown",
  );
});
test("offer counters require recognized eligibility unless completion explicit", () => {
  const values = { pointProgress: 10, pointProgressMax: 10 };
  assert.equal(snapshot.group([values]), "complete");
  for (const state of [undefined, null, "unknown-new-enum"]) {
    const value = { ...values };
    if (state !== undefined) value.exclusiveLockedFeatureStatus = state;
    assert.equal(
      snapshot.group([value], { requireEligibility: true }),
      "unknown",
    );
  }
  assert.equal(
    snapshot.group([{ ...values, exclusiveLockedFeatureStatus: "unlocked" }], {
      requireEligibility: true,
    }),
    "complete",
  );
  assert.equal(
    snapshot.group([{ ...values, complete: true }], {
      requireEligibility: true,
    }),
    "complete",
  );
});
test("extra activity overflow cannot silently report first thirty complete", () => {
  const offers = Array.from({ length: 31 }, (_, i) => ({
    offerId: "SocialMedia" + i,
    isCompleted: i < 30,
  }));
  assert.throws(() => extra.plan(offers, []), /activity_inventory_limit/);
});
test("bundled exact GPL parser needs no upstream installation", () => {
  const { loadParser } = require("../platforms/rewards/parser_loader.cjs");
  const parser = loadParser();
  const payload = JSON.stringify({
    offerId: "fixture",
    points: 3,
    isCompleted: true,
  });
  const html =
    "<script>self.__next_f.push([1," + JSON.stringify(payload) + "])</script>";
  assert.equal(parser.snapshotPage(html).offers[0].isCompleted, true);
  const file = path.join(
    __dirname,
    "../platforms/rewards/vendor/rewards-parser/dist/browser/ReactFunc.js",
  );
  assert.equal(
    /\brequire\s*\(|\bimport\s*\(/.test(fs.readFileSync(file, "utf8")),
    false,
  );
});

test("real snapshot warning result stops full before subsequent mutations", async () => {
  const full = require("../platforms/rewards/full.cjs");
  const raw = {
    userInfo: { isRewardsUser: true },
    flyoutResult: {
      userStatus: {
        isRewardsUser: true,
        counters: {
          PCSearch: [{ pointProgress: 0, pointProgressMax: 3 }],
          MobileSearch: [],
        },
      },
      userWarnings: [{ name: "Fraud_UserWarning_BotScore_UX" }],
      morePromotions: [],
      exploreOnBingPromotions: [],
    },
  };
  const page = {
    url: () => common.DASHBOARD,
    goto: async () => {},
    locator: () => ({ count: async () => 0 }),
    getByRole: () => ({
      waitFor: async () => {},
      getAttribute: async (name) => (name === "aria-valuenow" ? "0" : "3"),
    }),
  };
  const deps = {
    ...common,
    withBrowser: async (_c, _s, _o, work) => work({}, page),
    readFlyout: async () => raw,
  };
  const out = await full.execute(
    { schema_version: 1, enabled: ["daily"] },
    {
      daily: async () =>
        assert.fail("restriction must stop before card action"),
    },
    { snapshot: () => snapshot.run(null, {}, {}, deps) },
  );
  assert.equal(out.report.snapshots.before.reason, "account_restricted");
  assert.equal(out.business.daily, "blocked");
});
test("extra native preflight stops account warning before card action", async () => {
  const f = fakeExtra({ restricted: true });
  const out = await extra.run(null, {}, f.parser, {}, f.deps);
  assert.equal(out.reason, "account_restricted");
  assert.equal(f.events.includes("click"), false);
});
test("future-dated real parser offer cannot become an eligible extra card", async () => {
  const f = fakeExtra();
  const parser = require("../platforms/rewards/parser_loader.cjs").loadParser();
  const payload = JSON.stringify({
    offerId: "SocialMediaFixture",
    title: "Fixture",
    hash: "fixture",
    date: "01/01/2099",
    isLocked: false,
    isCompleted: false,
  });
  const html =
    "<script>self.__next_f.push([1," + JSON.stringify(payload) + "])</script>";
  f.deps.boundedHtml = async () => html;
  assert.equal(parser.snapshotPage(html).offers[0].reportable, false);
  const out = await extra.run(null, {}, parser, {}, f.deps);
  assert.equal(f.events.includes("click"), false);
  assert.equal(out.business.social, "blocked");
});
test("confirmed social result survives a later goal authorization obstacle", async () => {
  let clicked = false,
    url = common.EARN;
  const target = {
    url: () => "https://www.youtube.com/watch?v=fixture",
    waitForLoadState: async () => {},
    waitForTimeout: async () => {},
    close: async () => {},
  };
  const link = {
    first() {
      return this;
    },
    getAttribute: async () => target.url(),
    click: async () => {
      clicked = true;
    },
  };
  const page = {
    url: () => url,
    goto: async (value) => {
      url = value;
    },
    waitForTimeout: async () => {},
    waitForEvent: async () => target,
    locator: (selector) =>
      selector === "main"
        ? { waitFor: async () => {} }
        : { filter: () => link },
    getByRole: () => ({
      count: async () => 1,
      waitFor: async () => {},
      isChecked: async () => false,
    }),
  };
  const offers = () => [
    {
      offerId: "SocialMediaFixture",
      title: "Social",
      isCompleted: clicked,
      isLocked: false,
    },
    {
      offerId: "10XMSRewards_a30081646",
      title: "Goal",
      isCompleted: false,
      isLocked: false,
    },
  ];
  const deps = {
    EARN: common.EARN,
    withBrowser: async (_c, _s, _o, work) =>
      work({ newPage: async () => page }, page),
    guard: async () => {},
    boundedHtml: async () => "fixture",
    readFlyout: async () => ({
      userInfo: { isRewardsUser: true },
      flyoutResult: {
        userStatus: { isRewardsUser: true },
        morePromotions: offers().map((o) => ({
          offerId: o.offerId,
          exclusiveLockedFeatureStatus: "unlocked",
        })),
        exploreOnBingPromotions: [],
      },
    }),
  };
  const out = await extra.run(
    null,
    {},
    { snapshotPage: () => ({ offers: offers() }) },
    { goal: { url: "https://rewards.bing.com/redeem/sku/fixture" } },
    deps,
  );
  assert.equal(clicked, true);
  assert.equal(out.reason, "human_required");
  assert.equal(out.business.social, "complete");
  assert.equal(out.business.goal, "unknown");
});
