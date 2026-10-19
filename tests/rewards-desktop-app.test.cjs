"use strict";
const test = require("node:test"), assert = require("node:assert/strict");
const app = require("../platforms/rewards/desktop_app.cjs");
const {loadParser} = require("../platforms/rewards/parser_loader.cjs");
const {validateDetails} = require("../common/details.cjs");
const parent = "WW_pcparent_RewardsApp_weekly_Exclusive_Octw2_2026_punchcard";
const days = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
const children = () => days.map((day, i) => ({
  offerId: `WW_pcchild${i + 2}_urlreward_${day}_RewardsApp_weekly_Exclusive_Octw2_2026_punchcard`,
  hash: "hash_" + day, isCompleted: false, isLocked: !["Monday", "Tuesday"].includes(day),
  reportable: ["Monday", "Tuesday"].includes(day), name: day,
}));
function inventory(rows = children(), points = 0) {
  return {parent, title: "Rewards App weekly Exclusive Quest", children: rows,
    points: {current: points, max: 70}, tasks: {current: 1 + rows.filter(r => r.isCompleted).length, max: 8},
    balance: 100 + points};
}
function fixture({ackOnly = false, noCredit = false, ambiguous = false, prior = false} = {}) {
  const rows = children(), entries = new Map(), events = [];
  let points = 0, submitted = 0;
  if (prior) for (const row of rows.filter(r => !r.isLocked)) entries.set(row.offerId, "attempted");
  return {rows, entries, events, get submitted() {return submitted;},
    read: async () => inventory(rows.map(r => ({...r})), points),
    journalForQuest: id => {
      assert.equal(id, parent);
      return {has: id => entries.has(id), mark: async (id, state) => {
        entries.set(id, state); events.push([id, state]);
      }};
    },
    prepare: async () => {},
    submit: async (_q, row) => {
      assert.equal(entries.get(row.offerId), "attempted");
      submitted++;
      if (!ackOnly) rows.find(r => r.offerId === row.offerId).isCompleted = true;
      if (!ackOnly && !noCredit) points += 10;
      if (ambiguous) throw Error("POST transport timeout");
    },
    wait: async () => {},
  };
}
test("only unlocked daily children execute, each confirmed by its flag and weekly credit", async () => {
  const d = fixture(), out = await app.execute(d);
  assert.equal(d.submitted, 2);
  assert.equal(out.business.desktop_app_weekly, "complete");
  assert.equal(out.details.metrics.desktop_app_weekly.current, 20);
  assert.equal(out.details.metrics.desktop_app_weekly.max, 70);
  assert.equal(out.details.metrics.desktop_app_weekly.delta, 20);
  assert.equal(out.details.metrics.desktop_app_available.current, 2);
  assert.equal(out.details.items.filter(r => r.status === "blocked").length, 5);
  assert.equal(out.details.items.at(-1).status, "incomplete");
  validateDetails(out.details);
});
test("timeout after a credited POST reconciles without replay", async () => {
  const d = fixture({ambiguous: true});
  assert.equal((await app.execute(d)).business.desktop_app_weekly, "complete");
  assert.equal(d.submitted, 2);
  assert.deepEqual([...d.entries.values()], ["confirmed", "confirmed"]);
});
test("ACK and balance/aggregate progress do not replace corresponding child completion", async () => {
  const d = fixture({ackOnly: true});
  const read = d.read;
  d.read = async () => ({...await read(), points: {current: 20, max: 70}, balance: 120});
  const out = await app.execute(d);
  assert.equal(out.business.desktop_app_weekly, "unknown");
  assert.equal(d.submitted, 2);
  assert.deepEqual([...d.entries.values()], ["attempted", "attempted"]);
  assert.equal(out.details.items.filter(r => r.reason === "offer_not_credited").length, 2);
});
test("completed child without weekly points is unconfirmed", async () => {
  const d = fixture({noCredit: true});
  assert.equal((await app.execute(d)).business.desktop_app_weekly, "unknown");
  assert.deepEqual([...d.entries.values()], ["attempted", "attempted"]);
});
test("pending intent is not replayed; subsequent independent completion reconciles it", async () => {
  const d = fixture({prior: true});
  assert.equal((await app.execute(d)).business.desktop_app_weekly, "unknown");
  assert.equal(d.submitted, 0);
  for (const row of d.rows.filter(r => !r.isLocked)) row.isCompleted = true;
  d.read = async () => inventory(d.rows, 20);
  assert.equal((await app.execute(d)).business.desktop_app_weekly, "complete");
  assert.equal(d.submitted, 0);
  assert.deepEqual([...d.entries.values()], ["confirmed", "confirmed"]);
});
test("weekly rotation detected before submission prevents all writes", async () => {
  const d = fixture(); let reads = 0;
  d.read = async () => ({...inventory(), parent: ++reads === 1 ? parent : parent.replace("Octw2", "Octw3")});
  await assert.rejects(app.execute(d), /desktop_app_weekly_changed/);
  assert.equal(d.submitted, 0);
});
test("fully locked tasks remain blocked, and absent assigned card is not applicable", async () => {
  const d = fixture(); d.read = async () => inventory(d.rows.map(r => ({...r, isLocked: true})));
  assert.equal((await app.execute(d)).business.desktop_app_weekly, "blocked");
  assert.equal(d.submitted, 0);
  d.read = async () => null;
  assert.equal((await app.execute(d)).business.desktop_app_weekly, "not_applicable");
});
function flight(rows, points = 0) {
  const data = "/earn/quest/" + parent + " " + JSON.stringify({title: "Weekly quest"}) + " " +
    JSON.stringify(rows);
  return '<p>Desktop Rewards app.(' + points + '/70)</p><p>' +
    (1 + rows.filter(r => r.isCompleted).length) + '/8 tasks</p>' +
    '<script src="/_next/static/chunks/fixture.js?dpl=dpl_fixture_weekly"></script>' +
    '<script>self.__next_f.push([1,' + JSON.stringify(data) + '])</script>';
}
test("pinned parser supports omitted disabled field and excludes installation/other weeks", () => {
  const rows = children().map(({reportable, name, ...r}) => r);
  rows.push({offerId: "WW_pcchild1_urlreward_Install_RewardsApp_weekly_Exclusive_Octw2_2026_punchcard"},
    {...rows[1], offerId: rows[1].offerId.replace("Octw2", "Octw3")});
  const html = flight(rows), out = app.parse({offerId: parent, title: "Weekly"}, html, app.visibleText(html), loadParser());
  assert.equal(out.children.length, 7);
  assert.equal(out.children[1].isDisabled, false);
  assert.equal(out.children[1].reportable, true);
  assert.throws(() => app.parse({offerId: parent}, html, "not a quest", loadParser()), /progress_unavailable/);
});
test("completed React tile with no offer ID is confirmed by its keyed success checkmark", () => {
  const rows = children().filter(row => !row.offerId.includes("_Monday_")).map(({reportable, name, ...row}) => row);
  const node = ["$", "div", "2", {className: "flex flex-row gap-2 sm:gap-4", children: [
    ["$", "div", null, {children: ["$", "div", null, {className: "bg-statusSuccessRewardsBg",
      children: ["$", "svg", null, {}]}]}],
    ["$", "div", null, {children: "Great Pyramids of Giza"}],
  ]}];
  const html = flight(rows, 10) + '<script>self.__next_f.push([1,' + JSON.stringify("\n4b:" + JSON.stringify(node) + "\n") + '])</script>';
  const out = app.parse({offerId: parent, title: "Weekly"}, html, app.visibleText(html), loadParser());
  assert.equal(out.children.length, 7);
  assert.equal(out.children.find(row => row.offerId.includes("_Monday_")).isCompleted, true);
  const d = fixture({prior: true});
  d.read = async () => ({...out, balance: 110});
  d.submit = () => assert.fail("uncertain Tuesday must not replay");
  return app.execute(d).then(result => {
    assert.equal(d.entries.get(children()[1].offerId), "confirmed");
    assert.equal(result.business.desktop_app_weekly, "unknown");
  });
});
test("HTTP binding sends current server action and preserves browser origins without launching Chromium", async () => {
  const rows = children(), entries = new Map(), state = {cookies: [], origins: [{origin: "https://rewards.bing.com", localStorage: [{name: "kept", value: "yes"}]}]};
  let posts = 0, disposed = 0, contextDisposed = 0, handoff;
  const http = {
    fetch: async (url, args) => {
      if (args.method === "POST") {
        assert.equal(url, "https://rewards.bing.com/earn/quest/" + parent);
        assert.equal(args.headers["X-Deployment-Id"], "dpl_fixture_weekly");
        assert.equal(args.headers.Origin, "https://rewards.bing.com");
        assert.equal(args.headers["Next-Action"], "a".repeat(40));
        assert.equal(args.maxRedirects, 0);
        const [hash, type, attributes] = JSON.parse(args.data);
        const row = rows.find(r => r.offerId === attributes.offerid);
        assert.equal(entries.get(row.offerId), "attempted");
        assert.equal(hash, row.hash); assert.equal(type, 11);
        assert.equal(attributes.timezoneOffset, "-480");
        row.isCompleted = true; posts++;
      }
      const text = url.includes("fixture.js") ? `createServerReference("${"a".repeat(40)}",callServer,"reportActivity")` : flight(rows, posts * 10);
      return {status: () => 200, body: async () => Buffer.from(text), dispose: async () => disposed++};
    },
    storageState: async () => ({cookies: [{name: "refreshed"}], origins: []}),
    dispose: async () => contextDisposed++,
  };
  const out = await app.run({launch() {assert.fail("unexpected Chromium");}}, state, loadParser(), {
    timezoneOffset: -480, interaction: {enabled: false}, contextOptions: {userAgent: "existing Linux device"},
    requestFactory: async options => {
      assert.equal(options.storageState, state);
      assert.equal(options.userAgent, "existing Linux device " + app.APP_TOKEN);
      assert.equal(options.ignoreHTTPSErrors, false);
      return http;
    },
    journalForQuest: () => ({has: key => entries.has(key), mark: async (key, value) => entries.set(key, value)}),
    onVerifiedState: async value => handoff = value,
  }, {assertAccountAvailable: raw => raw, readFlyout: async () => ({flyoutResult: {userStatus: {availablePoints: 100 + posts * 10}}}), recordObstacle: () => {}});
  assert.equal(out.business.desktop_app_weekly, "complete");
  assert.equal(posts, 2);
  assert.equal(contextDisposed, 1);
  assert.ok(disposed > 2);
  assert.deepEqual(handoff.origins, state.origins);
  assert.deepEqual(handoff.cookies, [{name: "refreshed"}]);
});
test("unavailable HTTP inventory closes context and performs no POST", async () => {
  let closed = 0;
  const out = await app.run(null, {}, loadParser(), {readOnly: true, requestFactory: async () => ({
    fetch: async (_url, args) => {
      assert.notEqual(args.method, "POST");
      return {status: () => 503, body: async () => Buffer.from("Unavailable"), dispose: async () => {}};
    }, dispose: async () => closed++,
  })}, {assertAccountAvailable: raw => raw, readFlyout: async () => ({}), recordObstacle: () => {}});
  assert.equal(out.execution, "failed");
  assert.equal(out.business.desktop_app_weekly, "unknown");
  assert.equal(closed, 1);
});
