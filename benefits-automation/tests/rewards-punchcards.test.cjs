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
test("server action binds the deployment from the current page before submission", async () => {
  const calls=[];
  const page={evaluate:async (_fn,args)=>{
    if(typeof args==='number')return '<script src="/_next/static/chunks/current.js?dpl=dpl_fixture_20261009"></script>';
    calls.push(args);return {status:200,text:'1:true'};
  }};
  await a.request(page,'/earn',{method:'POST',headers:{'Next-Action':'a'.repeat(40)},body:'[]'});
  assert.equal(calls.length,1);
  assert.equal(calls[0].headers['X-Deployment-Id'],'dpl_fixture_20261009');
  assert.equal(calls[0].body,'[]');
  const absent={evaluate:async (_fn,args)=>{
    if(typeof args==='number')return '<main>Loading</main>';
    throw Error('unexpected_submission');
  }};
  await assert.rejects(a.request(absent,'/earn',{method:'POST',body:'[]'}),/deployment_evidence_unavailable/);
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
test("loaded-only discovery checks every referenced script without fetching unrelated graph branches", async () => {
  const calls = [], parser = {extractActionIds: text => ({byName: text.includes("source") ? {reportActivity: "a".repeat(40)} : {}})};
  const ids = await a.discover(null, parser, "static/chunks/a.js static/chunks/b.js", async (_page, route) => {
    calls.push(route);
    return {status: 200, text: route.endsWith("a.js") ? "source static/chunks/unloaded.js" : "other"};
  }, {loadedOnly: true});
  assert.equal(ids.reportActivity, "a".repeat(40));
  assert.deepEqual(calls, ["/_next/static/chunks/a.js", "/_next/static/chunks/b.js"]);
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
    { offerid: id, isPromotional: "$undefined", timezoneOffset: "-480" },
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
      if (args === undefined) return -480;
      if (typeof args === "number") return html().replace("fixture.js", "fixture.js?dpl=dpl_fixture_20261009");
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

function nativeFixture({
  metadata = {},
  actionPresent = true,
  restricted = false,
  journal,
} = {}) {
  const parser = require("../platforms/rewards/parser_loader.cjs").loadParser();
  let posted = 0;
  const entries = new Map();
  journal ||= {
    has: (key) => entries.has(key),
    mark: async (key, value) => entries.set(key, value),
  };
  const page = {
    goto: async () => {},
    waitForTimeout: async () => {},
    evaluate: async (_fn, args) => {
      if (args === undefined) return -480;
      if (typeof args === "number") return (await deps.boundedHtml()).replace("fixture.js", "fixture.js?dpl=dpl_fixture_20261009");
      if (args.method === "POST") {
        posted++;
        return { status: 200, text: "1:true" };
      }
      return {
        status: 200,
        text: actionPresent
          ? `createServerReference("${"a".repeat(40)}",callServer,"reportActivity")`
          : "no action IDs",
      };
    },
  };
  const deps = {
    EARN: "https://rewards.bing.com/earn",
    withBrowser: async (_c, _s, _o, work) => work({}, page),
    guard: async () => {},
    recordObstacle: () => {},
    boundedHtml: async () =>
      '<script src="/_next/static/chunks/fixture.js"></script><script>self.__next_f.push([1,' +
      JSON.stringify(
        "/earn/quest/" +
          p.PARENT +
          (posted ? " 1/1 tasks " : " 0/1 tasks ") +
          JSON.stringify({ ...child, ...metadata, isCompleted: posted > 0 }),
      ) +
      "])</script>",
    readFlyout: async () => ({
      userInfo: { isRewardsUser: true },
      flyoutResult: {
        userStatus: { isRewardsUser: true },
        userWarnings: restricted
          ? [{ name: "Fraud_UserWarning_BotScore_UX" }]
          : [],
      },
    }),
  };
  return {
    journal,
    entries,
    posted: () => posted,
    run: (options = {}) =>
      p.run(null, {}, parser, { journal, ...options }, deps),
  };
}
test("native metadata preserves search deferral and default manual claim gate", async () => {
  for (const metadata of [
    { promotionType: "search" },
    { attributes: { type: "search" } },
    { activityProgressMax: 3 },
    { destinationUrl: "https://rewards.bing.com/redeem/sku/fixture" },
  ]) {
    const f = nativeFixture({ metadata });
    await f.run();
    assert.equal(f.posted(), 0);
    assert.equal(f.entries.size, 0);
  }
  const allowed = nativeFixture({
    metadata: { destinationUrl: "https://rewards.bing.com/redeem/sku/fixture" },
  });
  assert.equal(
    (await allowed.run({ autoClaim: true })).business.punchcards,
    "complete",
  );
  assert.equal(allowed.posted(), 1);
});
test("missing action or invalid offset leaves no intent and a later valid run can submit", async () => {
  for (const options of [{ actionPresent: false }, { offset: 900 }]) {
    const f = nativeFixture(options);
    await f.run(options.offset ? { timezoneOffset: options.offset } : {});
    assert.equal(f.posted(), 0);
    assert.equal(f.entries.size, 0);
    const valid = nativeFixture({ journal: f.journal });
    assert.equal((await valid.run()).business.punchcards, "complete");
    assert.equal(valid.posted(), 1);
  }
});
test("native punchcard preflight stops a flyout restriction before journal or POST", async () => {
  const f = nativeFixture({ restricted: true });
  assert.equal((await f.run()).reason, "account_restricted");
  assert.equal(f.posted(), 0);
  assert.equal(f.entries.size, 0);
});
test("actual parser cannot hide conflicting action IDs within one chunk", async () => {
  const parser = require("../platforms/rewards/parser_loader.cjs").loadParser();
  for (const form of ["create", "register"]) {
    const reference = (id) =>
      form === "create"
        ? `createServerReference("${id}",callServer,"reportActivity")`
        : `registerServerReference(fn,"${id}","reportActivity")`;
    await assert.rejects(
      a.discover({}, parser, "static/chunks/fixture.js", async () => ({
        status: 200,
        text: reference("a".repeat(40)) + ";" + reference("b".repeat(40)),
      })),
      /ambiguous_action_id/,
    );
    const same = reference("a".repeat(40));
    assert.equal(
      (
        await a.discover({}, parser, "static/chunks/fixture.js", async () => ({
          status: 200,
          text: same + ";" + same,
        }))
      ).reportActivity,
      "a".repeat(40),
    );
  }
});
