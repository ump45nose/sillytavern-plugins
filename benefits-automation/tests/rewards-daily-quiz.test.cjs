const test = require("node:test");
const assert = require("node:assert/strict");
const quiz = require("../platforms/rewards/daily_quiz.cjs");
const offerId = "Gamification_DailySet_20261020_Child2";
const quizId = "REWARDSQUIZ_ENUS_MicrosoftRewardsQuizCB_20261020";
function href(question, choice, id = offerId) {
  const filters = `BTEPOKey:"${quizId}" BTQID:"${quizId}" BTOID:"${id}" BTQI:"${question}" BTCI:"${choice}"`;
  return "https://www.bing.com/search?q=fixture&filters=" + encodeURIComponent(filters);
}
test("only first-party quiz links bound to the current daily offer are actionable", () => {
  const landing = "https://www.bing.com/search?filters=" + encodeURIComponent(
    `BTEPOKey:"${quizId}" BTROID:"${offerId}"`);
  assert.equal(quiz.destination(landing, offerId), true);
  assert.equal(quiz.destination(landing, "another_offer"), false);
  assert.equal(quiz.answer(href(0, 1), offerId).choice, 1);
  for (const bad of [href(0, 1, "another_offer"), href(0, 1).replace("www.bing.com", "evil.invalid"),
      href(0, 1) + "&filters=duplicate", href(10, 1),
      href(0, 1) + encodeURIComponent(' BTOID:"another_offer"'),
      href(0, 1).replace("https://", "https://user@")])
    assert.equal(quiz.answer(bad, offerId), null);
});
function fixture({failClick = false, wrongOffer = false, obstacle = false} = {}) {
  let question = 0, summary = false;
  const clicks = [], entries = new Map(), events = [];
  const journal = {has: key => entries.has(key), mark: async (key, state) => {
    entries.set(key, state); events.push("intent");
  }};
  const next = {count: async () => Number(summary), click: async () => {
    question++; summary = false; events.push("next");
  }};
  const links = {evaluateAll: async () => question >= 3 ? [] : [0,1,2].map(choice =>
    ({href: href(question, choice, wrongOffer ? "another_offer" : offerId)})),
  nth: choice => ({click: async () => {
    assert.equal(events.at(-1), "intent");
    clicks.push([question, choice]);
    if (failClick) throw Error("network_failure");
    summary = true;
  }})};
  const card = {count: async () => question < 3 ? 1 : 0,
    locator: selector => selector.includes("next") ? next : links};
  const page = {locator: () => card, waitForLoadState: async () => {}};
  const options = {journal, guard: async () => {if (obstacle) throw Error("human_required");},
    pacing: {pause: async () => {}, review: async () => {}}};
  return {page, options, clicks, entries, events};
}
test("visible questions continue through answer summaries and Next controls", async () => {
  const f = fixture();
  await quiz.finish(f.page, {offerId}, f.options);
  assert.deepEqual(f.clicks, [[0,0],[1,0],[2,0]]);
  assert.equal(f.entries.size, 3);
  assert.equal(f.events.filter(x => x === "next").length, 3);
});
test("a failed answer retains its intent and never retries that same choice", async () => {
  const f = fixture({failClick: true});
  await assert.rejects(quiz.finish(f.page, {offerId}, f.options), /network_failure/);
  await assert.rejects(quiz.finish(f.page, {offerId}, f.options), /network_failure/);
  assert.deepEqual(f.clicks, [[0,0],[0,1]]);
  assert.equal(f.entries.size, 2);
});
test("an independent task readback ends answering as soon as this offer is complete", async () => {
  const f = fixture();
  await quiz.finish(f.page, {offerId}, {...f.options, confirmed: async () => true});
  assert.deepEqual(f.clicks, [[0,0]]);
  assert.equal(f.events.includes("next"), false);
});
test("unknown quiz identity or a login obstacle prevents answering", async () => {
  for (const config of [{wrongOffer: true}, {obstacle: true}]) {
    const f = fixture(config);
    await assert.rejects(quiz.finish(f.page, {offerId}, f.options));
    assert.equal(f.clicks.length, 0);
  }
});
