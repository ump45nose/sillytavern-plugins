"use strict";
// Desktop protocol observed in Microsoft's official macOS Rewards 1.4.56 client.
// Only the weekly URL-reward quest is handled; the client is never installed/run.
const path = require("node:path");
const common = require("./browser_common.cjs");
const actions = require("./server_actions.cjs");
const trace = require("./telemetry.cjs");
const interaction = require("./interaction.cjs");
const {metric} = require("../../common/details.cjs");
const CAPABILITY = "desktop_app_weekly";
const APP_TOKEN = "MSRewards/Desktop/1.4.56";
const DESKTOP_UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 " +
  "(KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36";
const PARENT = /^WW_pcparent_RewardsApp_weekly_Exclusive_([A-Za-z0-9_]+)_punchcard$/;
const CHILD = /^WW_pcchild[2-8]_urlreward_(Sunday|Monday|Tuesday|Wednesday|Thursday|Friday|Saturday)_RewardsApp_weekly_Exclusive_([A-Za-z0-9_]+)_punchcard$/;
const DAYS = {Sunday: "周日", Monday: "周一", Tuesday: "周二", Wednesday: "周三",
  Thursday: "周四", Friday: "周五", Saturday: "周六"};
function appOptions(options = {}) {
  return {...options, contextOptions: {...options.contextOptions,
    userAgent: (options.contextOptions?.userAgent || DESKTOP_UA) + " " + APP_TOKEN}};
}
function progress(text, maximum) {
  // The numeric counters stay stable when the page translates its task labels.
  const values = new Set([...text.matchAll(/\b(\d+)\s*\/\s*(\d+)\b/g)]
    .filter(match => Number(match[2]) === maximum).map(match => Number(match[1])));
  if (values.size !== 1) return null;
  const current = [...values][0];
  return current <= maximum ? {current, max: maximum} : null;
}
function parse(parent, html, text, parser) {
  const week = parent.offerId.match(PARENT)[1];
  const points = progress(text, 70), tasks = progress(text, 8);
  const children = parser.snapshotQuestPage(html).filter(row => {
    const match = row.offerId.match(CHILD);
    return match && match[2] === week;
  }).map(row => ({...row, name: "桌面 App " + DAYS[row.offerId.match(CHILD)[1]] + "活动"}));
  // Completed tiles omit offerId/hash entirely. Their keyed React row still
  // contains the day's title and the explicit success-circle/checkmark.
  const flight = parser.concatFlightChunks(html);
  const records = new Map([...flight.matchAll(/^([a-f0-9]+):(\[[^\n]+)$/gm)]
    .map(match => [match[1], JSON.parse(match[2])]));
  const resolve = value => typeof value === "string" && /^\$L?[a-f0-9]+$/.test(value) ?
    records.get(value.replace(/^\$L?/, "")) : value;
  for (const root of records.values()) {
    // React can inline the same keyed tile in its parent record instead of
    // emitting a separate Flight record for it. Inspect both representations.
    const pending = [root];
    while (pending.length) {
      const node = pending.pop();
      if (!node || typeof node !== "object") continue;
      pending.push(...Object.values(node).filter(value => value && typeof value === "object"));
      if (!Array.isArray(node) || node[0] !== "$" || node[1] !== "div" ||
          !/^[1-7]$/.test(node[2]) || node[3]?.className !== "flex flex-row gap-2 sm:gap-4") continue;
      const circle = resolve(resolve(resolve(node[3].children)?.[0])?.[3]?.children);
      if (!circle?.[3]?.className?.split(" ").includes("bg-statusSuccessRewardsBg") ||
          resolve(circle[3].children)?.[1] !== "svg") continue;
      const day = Object.keys(DAYS)[Number(node[2]) - 1];
      const offerId = `WW_pcchild${Number(node[2]) + 1}_urlreward_${day}_RewardsApp_weekly_Exclusive_${week}_punchcard`;
      const completed = {offerId, hash: null, points: 10, isCompleted: true,
        isLocked: false, isDisabled: false, reportable: false, name: "桌面 App " + DAYS[day] + "活动"};
      const existing = children.find(row => row.offerId === offerId);
      if (existing) Object.assign(existing, completed);
      else children.push(completed);
    }
  }
  // The installation tile has zero points and is not an earning activity.
  if (!points || !tasks || children.length !== 7)
    throw Error("desktop_app_progress_unavailable");
  return {parent: parent.offerId, title: parent.title, children,
    points, tasks};
}
function summary(current, before = current, uncertain = new Set()) {
  if (!current) return {execution: "ok", reason: "desktop_app_weekly_not_assigned",
    business: {[CAPABILITY]: "not_applicable"}, details: {metrics: {}, items: []}};
  const available = current.children.filter(row => row.isCompleted || (!row.isLocked && !row.isDisabled));
  const completed = current.children.filter(row => row.isCompleted);
  const credited = current.points.current >= completed.length * 10;
  const state = !credited || available.some(row => uncertain.has(row.offerId)) ? "unknown" :
    !available.length ? "blocked" : available.every(row => row.isCompleted) ? "complete" : "incomplete";
  const items = current.children.map(row => ({id: row.offerId, name: row.name,
    status: uncertain.has(row.offerId) || (row.isCompleted && !credited) ? "unknown" :
      row.isCompleted ? "complete" : row.isLocked || row.isDisabled ? "blocked" : "incomplete",
    reason: uncertain.has(row.offerId) || (row.isCompleted && !credited) ? "offer_not_credited" :
      row.isLocked || row.isDisabled ? "platform_locked" : "fresh_readback"}));
  items.push({id: "desktop_app_weekly_quest", name: current.title,
    status: current.points.current >= current.points.max ? "complete" : "incomplete",
    reason: "weekly_progress", url: common.EARN + "/quest/" + current.parent});
  return {execution: "ok", reason: state === "complete" ? "desktop_app_weekly_complete" :
    state === "blocked" ? "desktop_app_weekly_locked" : "desktop_app_weekly_pending",
    business: {[CAPABILITY]: state}, details: {metrics: {
      desktop_app_weekly: metric("points", current.points.current, current.points.max,
        before.points.current, current.points.current, current.points.current - before.points.current),
      desktop_app_weekly_tasks: metric("count", current.tasks.current, current.tasks.max),
      desktop_app_available: metric("count", available.filter(row => row.isCompleted).length, available.length),
      balance: metric("points", current.balance, null, before.balance, current.balance,
        current.balance - before.balance),
    }, items}};
}
async function execute(driver) {
  const before = await driver.read();
  if (!before) return summary(null);
  let current = before;
  const journal = driver.journalForQuest(before.parent), uncertain = new Set();
  if (before.points.current >= before.children.filter(row => row.isCompleted).length * 10)
    for (const row of before.children.filter(row => row.isCompleted))
      await journal.mark(row.offerId, "confirmed");
  for (const row of before.children.filter(row => !row.isCompleted && !row.isLocked && !row.isDisabled)) {
    current = await driver.read();
    if (current?.parent !== before.parent) throw Error("desktop_app_weekly_changed");
    const child = current.children.find(value => value.offerId === row.offerId);
    if (child.isCompleted) {
      if (current.points.current >= current.children.filter(value => value.isCompleted).length * 10)
        await journal.mark(child.offerId, "confirmed");
      continue;
    }
    if (child.isLocked || child.isDisabled) continue;
    if (!child.reportable || journal.has(child.offerId)) {
      uncertain.add(child.offerId);
      continue;
    }
    await driver.prepare(current, child);
    await journal.mark(child.offerId, "attempted");
    trace.emit("journal.intent", {capability: CAPABILITY,
      offer_ref: trace.reference(child.offerId), state: "attempted"});
    const creditedBefore = current.points.current;
    try {await driver.submit(current, child);}
    catch (error) {
      trace.failure("promotion.submit", error, {capability: CAPABILITY});
      if (error.details?.code) throw error;
    }
    let confirmed = false;
    for (let attempt = 0; attempt < 3; attempt++) {
      await driver.wait();
      current = await driver.read();
      if (current?.parent !== before.parent) throw Error("desktop_app_weekly_changed");
      confirmed = current.children.find(value => value.offerId === child.offerId).isCompleted &&
        current.points.current >= creditedBefore + 10;
      if (confirmed) break;
    }
    if (confirmed) await journal.mark(child.offerId, "confirmed");
    else uncertain.add(child.offerId);
    trace.emit("promotion.readback", {capability: CAPABILITY,
      offer_ref: trace.reference(child.offerId), complete: confirmed});
  }
  return summary(current, before, uncertain);
}
function visibleText(html) {
  return html.replace(/<script\b[\s\S]*?<\/script>/gi, " ")
    .replace(/<style\b[\s\S]*?<\/style>/gi, " ").replace(/<[^>]*>/g, " ");
}
async function run(_chromium, state, parser, options = {}, deps = common) {
  const pacing = options.pacing || interaction.create(options.interaction);
  let observed, http;
  try {
    let factory = options.requestFactory;
    if (!factory) {
      common.dependency(process.env.REWARDS_ROOT);
      const request = require(path.join(process.env.REWARDS_ROOT, "node_modules/patchright")).request;
      factory = value => request.newContext(value);
    }
    http = await factory({storageState: state,
      userAgent: appOptions(options).contextOptions.userAgent, ignoreHTTPSErrors: false,
      ...(options.proxy ? {proxy: {server: options.proxy}} : {})});
    trace.instrumentRequest(http);
    async function send(route, args = {}) {
      actions.safePath(route);
      const {body, ...requestOptions} = args;
      const response = await http.fetch("https://rewards.bing.com" + route,
        {...requestOptions, data: body, timeout: 20000, maxRedirects: 0});
      try {
        const body = await response.body();
        if (body.length > common.MAX_HTML) throw Error("response_too_large");
        return {status: response.status(), text: body.toString()};
      } finally {await response.dispose();}
    }
    async function html(route) {
      const response = await send(route);
      if (response.status !== 200) throw Error("desktop_app_weekly_unavailable");
      return response.text;
    }
    async function read() {
      const raw = deps.assertAccountAvailable(await deps.readFlyout({request: http}), options.region);
      const overview = await html("/earn");
      const parents = parser.snapshotQuestList(overview).filter(row => PARENT.test(row.offerId));
      if (!parents.length) {
        if (!parser.snapshotPage(overview).offers.length) throw Error("desktop_app_weekly_unavailable");
        return null;
      }
      if (parents.length !== 1) throw Error("desktop_app_weekly_unavailable");
      const text = await html("/earn/quest/" + parents[0].offerId);
      observed = {...parse(parents[0], text, visibleText(text), parser), html: text,
        balance: raw.flyoutResult.userStatus.availablePoints};
      return observed;
    }
    let out;
    if (options.readOnly) out = summary(await read());
    else {
      let ids, deployment;
      const offset = options.timezoneOffset === undefined ? new Date().getTimezoneOffset() : Number(options.timezoneOffset);
      out = await execute({read, journalForQuest: options.journalForQuest,
        async prepare(current, child) {
          ids ||= await actions.discover(null, parser, current.html, (_page, route) => send(route), {loadedOnly: true});
          actions.validateSubmission(ids.reportActivity, current.parent, child, offset);
          deployment = parser.buildId(current.html);
          if (!deployment) throw Error("deployment_evidence_unavailable");
          await pacing.pause(null, "action");
        },
        submit: (current, child) => actions.submit(null, parser, ids.reportActivity,
          current.parent, child, offset, (_page, route, args) => send(route, {
            ...args, headers: {...args.headers, "X-Deployment-Id": deployment,
              Origin: "https://rewards.bing.com", Referer: common.EARN + "/quest/" + current.parent}})),
        wait: () => new Promise(resolve => setTimeout(resolve, 3000)),
      });
    }
    if (out.execution === "ok" && options.onVerifiedState)
      await options.onVerifiedState({...state, cookies: (await http.storageState()).cookies});
    return out;
  } catch (error) {
    trace.failure("stage", error, {capability: CAPABILITY});
    deps.recordObstacle(error, {capability: CAPABILITY, phase: "weekly_quest"});
    return {...summary(observed), execution: "failed",
      reason: error.details?.code || (error.message.startsWith("desktop_app_") ?
        error.message : "desktop_app_weekly_unavailable"), business: {[CAPABILITY]: "unknown"}};
  } finally {await http?.dispose();}
}
async function main() {
  const dir = process.env.BENEFITS_STATE_DIR;
  const fs = require("node:fs"), file = path.join(dir, "native-config.json");
  const config = fs.existsSync(file) ? common.boundedJson(file, 65536) : {};
  const out = await run(common.dependency(process.env.REWARDS_ROOT), common.readState(dir),
    require("./parser_loader.cjs").loadParser(), {proxy: process.env.REWARDS_PROXY,
      region: config.region, contextOptions: config.desktop, timezoneOffset: config.timezoneOffset,
      interaction: config.interaction, journalForQuest: parent => require("./punchcards.cjs").journal(
        path.join(dir, "desktop-app-weekly-" + trace.reference(parent) + ".json"))});
  require("../../common/result.cjs").publish(out.execution, out.reason, out.business, out.details);
}
module.exports = {APP_TOKEN, appOptions, parse, visibleText, summary, execute, run};
if (require.main === module) main().catch(error => {
  trace.failure("run", error, {capability: CAPABILITY});
  require("../../common/result.cjs").publish("failed", "desktop_app_weekly_unavailable",
    {[CAPABILITY]: "unknown"});
});
