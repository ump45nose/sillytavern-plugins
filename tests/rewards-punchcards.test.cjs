"use strict";
const test = require("node:test"),
  assert = require("node:assert/strict");
const p = require("../platforms/rewards/punchcards.cjs");
const a = require("../platforms/rewards/server_actions.cjs");
const id = "WW_pcchild_task",
  child = {
    offerId: id,
    hash: "livehash",
    reportable: true,
    isCompleted: false,
    isLocked: false,
    isDisabled: false,
  };
function fixture({
  completeAfter = true,
  throwWrite = false,
  prior = false,
} = {}) {
  let submitted = 0,
    observations = 0;
  const events = [];
  const card = {
    parentPromotion: { offerId: p.PARENT, complete: false },
    childPromotions: [
      { offerId: id, exclusiveLockedFeatureStatus: "unlocked" },
    ],
  };
  return {
    events,
    get submitted() {
      return submitted;
    },
    journal: { has: () => prior, mark: async (_, state) => events.push(state) },
    inventory: async () => [card],
    children: async () => {
      observations++;
      return [
        {
          ...child,
          isCompleted: submitted > 0 && completeAfter && observations > 2,
        },
      ];
    },
    submit: async () => {
      events.push("submit");
      submitted++;
      if (throwWrite) throw Error("timeout");
    },
    wait: async () => {},
  };
}
test("source onboarding allowlist and single journaled submission with delayed confirmation", async () => {
  const d = fixture();
  const out = await p.execute(d);
  assert.equal(d.submitted, 1);
  assert.deepEqual(d.events, ["attempted", "submit", "confirmed"]);
  assert.equal(out.status, "incomplete");
});
test("ambiguous POST reconciles success without replay", async () => {
  const d = fixture({ throwWrite: true });
  await p.execute(d);
  assert.equal(d.submitted, 1);
  assert.equal(d.events.at(-1), "confirmed");
});
test("prior attempted action never replays", async () => {
  const d = fixture({ prior: true });
  assert.equal((await p.execute(d)).status, "unknown");
  assert.equal(d.submitted, 0);
});
test("ACK without child completion is unknown", async () => {
  const d = fixture({ completeAfter: false });
  assert.equal((await p.execute(d)).status, "unknown");
  assert.deepEqual(d.events, ["attempted", "submit"]);
});
test("claim toggle, search quota, unknown eligibility and locked child", () => {
  const meta = { exclusiveLockedFeatureStatus: "unlocked" };
  assert.equal(
    p.classify({ ...child, offerId: "pcchild_claim" }, meta),
    "manual_claim",
  );
  assert.equal(
    p.classify({ ...child, offerId: "pcchild_claim" }, meta, true),
    "eligible",
  );
  assert.equal(
    p.classify(child, { ...meta, activityProgressMax: 3 }),
    "deferred",
  );
  assert.equal(p.classify(child, {}), "unknown");
  assert.equal(p.classify({ ...child, isLocked: true }, meta), "blocked");
});
test("unrelated parent and missing inventory cannot imply completion", async () => {
  const d = fixture();
  d.inventory = async () => [];
  assert.equal((await p.execute(d)).status, "unknown");
  assert.equal(d.submitted, 0);
});
test("unsafe server routes rejected", () => {
  for (const path of [
    "/earn/quest/../../x",
    "//evil.invalid/a",
    "/_next/static/chunks/../x.js",
    "/earn?token=x",
  ])
    assert.throws(() => a.safePath(path));
});
test("bounded sequential action discovery rejects conflicting action IDs", async () => {
  let calls = 0;
  const parser = {
    extractActionIds: (text) => ({ byName: { reportActivity: text } }),
  };
  await assert.rejects(
    a.discover(
      {},
      parser,
      "static/chunks/a.js static/chunks/b.js",
      async () => ({
        status: 200,
        text: (++calls === 1 ? "a" : "b").repeat(40),
      }),
    ),
    /ambiguous/,
  );
  assert.equal(calls, 2);
});
test("real server action binding sends exact source payload once", async () => {
  let sent;
  await a.submit(
    {},
    { questRouterStateTree: () => "tree" },
    "a".repeat(40),
    p.PARENT,
    child,
    -480,
    async (_, route, args) => {
      sent = { route, args };
      return { status: 200, text: "ACK" };
    },
  );
  assert.equal(sent.args.method, "POST");
  assert.deepEqual(JSON.parse(sent.args.body), [
    "livehash",
    11,
    { offerid: id, isPromotional: "$undefined", timezoneOffset: -480 },
  ]);
  assert.equal(sent.route, "/earn/quest/" + p.PARENT);
});

test("real vendored parser through native fake-browser binding confirms parent", async () => {
  const parser = require("../platforms/rewards/parser_loader.cjs").loadParser();
  let posted = 0,
    url = "";
  const page = {
    goto: async (value) => {
      url = value;
    },
    url: () => url,
    waitForTimeout: async () => {},
    evaluate: async (_fn, args) => {
      if (args.method === "POST") {
        posted++;
        return { status: 200, text: "1:true" };
      }
      return {
        status: 200,
        text: `createServerReference("${"a".repeat(40)}",callServer,"reportActivity")`,
      };
    },
  };
  const html = () => {
    const payload =
      "/earn/quest/" +
      p.PARENT +
      " " +
      (posted ? "1/1 tasks" : "0/1 tasks") +
      " " +
      JSON.stringify({ ...child, isCompleted: posted > 0 });
    return (
      '<script src="/_next/static/chunks/fixture.js"></script><script>self.__next_f.push([1,' +
      JSON.stringify(payload) +
      "])</script>"
    );
  };
  const d = fixture();
  const deps = {
    EARN: "https://rewards.bing.com/earn",
    withBrowser: async (_c, _s, _o, fn) => fn({}, page),
    guard: async () => {},
    boundedHtml: async () => html(),
    readFlyout: async () => ({
      userInfo: { isRewardsUser: true },
      flyoutResult: { userStatus: { isRewardsUser: true } },
    }),
    recordObstacle: () => {},
  };
  const out = await p.run(null, {}, parser, { journal: d.journal }, deps);
  assert.equal(out.business.punchcards, "complete");
  assert.equal(posted, 1);
});
