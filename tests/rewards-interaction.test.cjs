"use strict";
const test = require("node:test"), assert = require("node:assert/strict");
const interaction = require("../platforms/rewards/interaction.cjs"), search = require("../platforms/rewards/search.cjs");
const app = require("../platforms/rewards/app.cjs");
test("default randomized pauses respect search floor, configured delays and batch rest", async () => {
  const waits = [], page = {waitForTimeout: async ms => waits.push(ms)};
  for (const random of [() => 0, () => 0.999999]) {
    const pacing = interaction.create(undefined, {random});
    await pacing.pause(page, "stage");
    await pacing.pause(page, "action");
    await pacing.pause(page, "settle");
    await pacing.review(page);
    await pacing.cooldown(page, 0);
    await pacing.cooldown(page, 60000);
    for (const count of [0, 1, 7, 8, 9, 16]) await pacing.rest(page, count);
  }
  assert.deepEqual(waits, [2000,1500,1200,10000,30000,60000,45000,45000,
    5000,3500,2800,15000,42000,72000,75000,75000]);
});
test("typing uses actual sequential key input with bounded per-character delays", async () => {
  const calls = [], pacing = interaction.create(undefined, {random: () => 0.5});
  await pacing.type({waitForTimeout: async ms => calls.push(["wait",ms])}, {
    click: async () => calls.push(["click"]), fill: async value => calls.push(["fill",value]),
    pressSequentially: async (value, options) => calls.push(["key",value,options.delay]),
  }, "Aa中");
  assert.deepEqual(calls, [["wait",2500],["click"],["fill",""],["key","A",75],["key","a",75],["key","中",75]]);
});
test("a click scrolls into view and reading uses a bounded scroll and dwell", async () => {
  const calls = [], pacing = interaction.create(undefined, {random: () => 0});
  const page = {waitForTimeout: async ms => calls.push(["wait",ms]), mouse: {wheel: async (...args) => calls.push(["wheel",...args])}};
  await pacing.click(page, {scrollIntoViewIfNeeded: async () => calls.push(["scroll"]),
    click: async options => calls.push(["click", options])}, {timeout: 15000});
  await pacing.review(page, 30000);
  assert.deepEqual(calls, [["scroll"],["wait",1500],["click",{timeout: 15000,delay: 80}],["wheel",0,240],["wait",30000]]);
});
test("disabled pacing still honors an existing safety wait and rejects malformed configuration", async () => {
  const waits = [], pacing = interaction.create({enabled: false}, {sleep: async ms => waits.push(ms)});
  await pacing.pause(null, "stage"); await pacing.pause(null, "reading", 30000); await pacing.cooldown(null, 60000);
  assert.deepEqual(waits, [30000,60000]);
  for (const config of [{enabled: "yes"},{action: [3500,1500]},{action: [1,Infinity]}, {typing: [1,501]}, {breakEvery: 0}, {unknown: true}])
    assert.throws(() => interaction.configuration(config), /invalid_interaction_config/);
});
function searchFixture({challengeAfterTyping = false, interrupt = false} = {}) {
  let earned = 0, input = "", marked = false, presses = 0;
  const calls = [], pacing = interaction.create(undefined, {random: () => 0});
  const box = {waitFor: async () => {}, click: async () => {}, fill: async text => {input = text;},
    pressSequentially: async value => {input += value;}, press: async key => {
      assert.equal(key, "Enter"); assert.equal(marked, true); assert.equal(input, "fixture query");
      presses++; earned = 3;
    }};
  const page = {locator: () => box, waitForLoadState: async () => {}, waitForTimeout: async ms => {
    calls.push(ms); if (interrupt) throw Error("page closed during delay");
  }};
  const obstacle = Object.assign(new Error("captcha"), {details: {code: "captcha"}});
  return {page, calls, pacing, presses: () => presses, marked: () => marked,
    observe: async () => ({desktop_search: {status: earned === 3 ? "complete" : "incomplete", earned, max: 3}}),
    deps: {guard: async () => {if (challengeAfterTyping && input) throw obstacle;}},
    journal: {has: () => false, mark: async () => {marked = true;}}, obstacle};
}
test("human input keeps persisted intent before Enter and waits before quota confirmation", async () => {
  const f = searchFixture();
  const out = await search.runSession(f.page, f.observe, "desktop", search.configuration(),
    ["fixture query"], f.deps, f.journal, f.pacing);
  assert.equal(out.business.desktop_search, "complete");
  assert.equal(f.presses(), 1);
  assert.deepEqual(f.calls, [1500,1200,30000]);
});
test("a challenge during typing or an interrupted pause cannot persist intent or submit", async () => {
  for (const options of [{challengeAfterTyping: true}, {interrupt: true}]) {
    const f = searchFixture(options);
    await assert.rejects(search.runSession(f.page, f.observe, "desktop", search.configuration(),
      ["fixture query"], f.deps, f.journal, f.pacing));
    assert.equal(f.marked(), false); assert.equal(f.presses(), 0);
  }
});
test("APP pacing runs before journal intent and cannot cause an unrecorded POST", async () => {
  let marked = false, submits = 0, pauses = 0;
  const raw = complete => ({response: {profile: {ruid: "fixture"}, balance: 100,
    promotions: [{attributes: {type: "sapphire", offerid: "fixture_offer", complete: String(complete)}}]}});
  const client = {read: async () => raw(submits > 0), submit: async () => {assert.equal(marked, true); submits++;}};
  const journal = {has: () => marked, mark: async () => {marked = true;}};
  const beforeSubmit = async () => {assert.equal(marked, false); pauses++;};
  const out = await app.runPromotions(client, journal, {beforeSubmit, wait: async () => {}});
  assert.equal(out.business.app_promotions, "complete"); assert.equal(submits, 1); assert.equal(pauses, 1);
  await app.runPromotions(client, journal, {beforeSubmit, wait: async () => {}});
  assert.equal(submits, 1); assert.equal(pauses, 1);
  marked = false; submits = 0;
  await assert.rejects(app.runPromotions(client, journal, {beforeSubmit: async () => {throw Error("pause interrupted");}}));
  assert.equal(marked, false); assert.equal(submits, 0);
});
