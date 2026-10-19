const test = require("node:test");
const assert = require("node:assert/strict");
const extra = require("../platforms/rewards/extra.cjs");
const common = require("../platforms/rewards/browser_common.cjs");

function exploreFixture(topic, { credited = true, navigationRace = false, targetChallenge = false, title = topic } = {}) {
  const id = `ENUS_${topic}_exploreonbing_activation_Evergreen`;
  const unrelated = "ENUS_videogames_exploreonbing_activation_Evergreen";
  const submitted = [];
  const marks = new Map([[id, "attempted"]]);
  let query;
  let raced = false;
  const page = {
    goto: async () => {},
    waitForTimeout: async () => {},
    locator: () => ({ waitFor: async () => {} }),
  };
  const target = {
    ...page,
    url: () => "https://www.bing.com/search",
    waitForLoadState: async () => {},
    close: async () => {},
    locator: () => ({
      waitFor: async () => {},
      fill: async (value) => { query = value; },
      press: async () => {
        // The adapter must record intent before issuing each search.
        const key = "query_" + require("node:crypto").createHash("sha256")
          .update(id + "\0" + query).digest("hex");
        assert.equal(marks.get(key), "attempted");
        submitted.push(query);
      },
    }),
  };
  const done = () => credited && submitted.length > 0;
  const parser = {
    snapshotPage: () => ({ offers: [
      { offerId: id, title, reportable: true, hash: "fixture",
        isCompleted: done(), isLocked: false },
      { offerId: unrelated, title: "Other task", isCompleted: true },
    ] }),
  };
  const deps = {
    EARN: common.EARN,
    withBrowser: async (_c, _s, _o, work) => {
      let pages = 0;
      return work({ newPage: async () => ++pages === 1 ? page : target }, page);
    },
    guard: async (current) => {
      if (navigationRace && current === target && !raced) {
        raced = true;
        throw Error("locator.count: Execution context was destroyed, most likely because of a navigation");
      }
      if (targetChallenge && current === target) throw new common.HumanRequired();
    },
    boundedHtml: async () => "fixture",
    readFlyout: async () => ({
      userInfo: { isRewardsUser: true },
      flyoutResult: {
        userStatus: { isRewardsUser: true },
        morePromotions: [],
        exploreOnBingPromotions: [
          { offerId: id, exclusiveLockedFeatureStatus: "unlocked",
            destinationUrl: "https://www.bing.com/search?q=fixture",
            complete: done(), pointProgress: done() ? 10 : 0, pointProgressMax: 10 },
          { offerId: unrelated, complete: true, pointProgress: 10, pointProgressMax: 10 },
        ],
      },
    }),
  };
  const options = { journal: {
    has: (key) => marks.has(key),
    mark: async (key, value) => marks.set(key, value),
  } };
  return { id, submitted, marks, run: () => extra.run(null, {}, parser, options, deps) };
}

for (const topic of ["flowerdelivery", "jobs", "restaurant", "petsupplies", "weather", "mattress",
    "creditcards", "flight", "insurance", "shopping"]) {
  test(`${topic} exploration searches and confirms its own task`, async () => {
    const f = exploreFixture(topic);
    const out = await f.run();
    assert.equal(out.business.explore, "complete");
    assert.deepEqual(f.submitted, [extra.QUERIES[topic][0]]);
    assert.equal(out.details.items.find(row => row.id === f.id).status, "complete");
    assert.equal(f.marks.get(f.id), "confirmed");
    await f.run();
    assert.equal(f.submitted.length, 1);
  });
}

test("read-only guard recovers a navigation race before submitting a search", async () => {
  const f = exploreFixture("weather", { navigationRace: true });
  const out = await f.run();
  assert.equal(out.business.explore, "complete");
  assert.deepEqual(f.submitted, [extra.QUERIES.weather[0]]);
});

test("navigation race recovery still stops at authentication obstacles", async () => {
  const f = exploreFixture("weather", { navigationRace: true, targetChallenge: true });
  const out = await f.run();
  assert.equal(out.reason, "human_required");
  assert.deepEqual(f.submitted, []);
});

test("uncredited exploration remains unknown and does not replay submitted searches", async () => {
  const f = exploreFixture("restaurant", { credited: false });
  const first = await f.run();
  assert.equal(first.business.explore, "unknown");
  assert.equal(first.details.items.find(row => row.id === f.id).reason, "offer_not_credited");
  assert.deepEqual(f.submitted, extra.QUERIES.restaurant);
  const second = await f.run();
  assert.equal(second.business.explore, "unknown");
  assert.deepEqual(f.submitted, extra.QUERIES.restaurant);
  assert.equal(f.marks.get(f.id), "attempted");
});

test("unrecognized exploration remains unsupported without submitting searches", async () => {
  const f = exploreFixture("unrecognized");
  const out = await f.run();
  assert.equal(out.business.explore, "unknown");
  assert.equal(out.details.items.find(row => row.id === f.id).reason, "search_topic_unsupported");
  assert.deepEqual(f.submitted, []);
});

for (const [id, title] of [["hotel", "Find places to stay!\u200b"],
  ["jewelry", "Shine bright"], ["realestate", "Houses near you"], ["sports", "Who won?"]]) {
  test(`${id} resolves the upstream title catalog without a hand-written topic`, async () => {
    const f = exploreFixture(id, {title});
    const out = await f.run();
    assert.equal(out.business.explore, "complete");
    assert.equal(f.submitted.length, 1);
    assert.equal(f.marks.get(f.id), "confirmed");
  });
}

test("the full pinned catalog resolves every title and metadata alias", () => {
  const topics = require("../platforms/rewards/topic_queries.cjs");
  const catalog = require("../platforms/rewards/vendor/rewards-parser/src/functions/bing-search-activity-queries.json");
  assert.equal(catalog.length, 74);
  for (const row of catalog) {
    assert.deepEqual(topics.resolve({title: `  ${row.title.toUpperCase()}\u200b  `}), row.queries);
    assert.deepEqual(topics.resolve({title: "localized", metadata: {title: row.title}}), row.queries);
  }
  assert.deepEqual(topics.resolve({offerId: "ENUS_jobs_exploreonbing_activation_Evergreen", title: "招聘"}),
    extra.QUERIES.jobs);
});
