"use strict";
const common = require("./browser_common.cjs");
const {loadParser} = require("./parser_loader.cjs");
const {metric} = require("../../common/details.cjs");
const PARTNERS = {bing: "bing_streak", bingapp: "app_streak"};
const LABELS = {bing: "必应连续打卡", bingapp: "APP连续打卡"};
function measure(row) {
  if (!row || row.activitiesTotal <= 0)
    return {status: "unknown", earned: null, max: null};
  return {status: !row.isEnabled ? "not_applicable" :
    row.isCurrentDayCompleted && row.activitiesCompleted >= row.activitiesTotal ? "complete" : "incomplete",
    earned: row.activitiesCompleted, max: row.activitiesTotal};
}
function summary(rows) {
  const business = {}, metrics = {}, items = [];
  for (const [partner, key] of Object.entries(PARTNERS)) {
    const row = rows.find(row => row.partner === partner), q = measure(row);
    business[key] = q.status;
    metrics[key] = metric("count", q.earned, q.max);
    metrics[key + "_days"] = metric("days", row?.completedDays, row?.totalDays);
    items.push({id: key, name: LABELS[partner], status: q.status,
      reason: q.status === "unknown" ? "streak_progress_unavailable" : "fresh_readback"});
  }
  return {business, details: {metrics, items}};
}
async function read(context) {
  const response = await context.request.get(common.DASHBOARD, {timeout: 20000, maxRedirects: 0});
  try {
    const bytes = await response.body();
    if (response.status() !== 200 || bytes.length > common.MAX_HTML)
      throw Error("streak_progress_unavailable");
    return loadParser().snapshotPage(bytes.toString()).streaks;
  } finally {await response.dispose();}
}
async function run(chromium, state, options = {}, deps = common) {
  let observed;
  try {
    return await deps.withBrowser(chromium, state, options, async (context, page) => {
      deps.assertAccountAvailable(await deps.readFlyout(context), options.region);
      const observe = async () => {
        observed = await (options.readStreaks || read)(context);
        return {bing_streak: measure(observed.find(row => row.partner === "bing"))};
      };
      const initial = await observe();
      let searchOut;
      if (initial.bing_streak.status === "incomplete") {
        await page.goto("https://www.bing.com/", {waitUntil: "domcontentloaded", timeout: 45000});
        await deps.guard(page);
        const search = require("./search.cjs");
        searchOut = await search.runSession(page, observe, "desktop",
          search.configuration({...options.search, maxSearches: 1}),
          options.search?.queries || require("./vendor/rewards-parser/src/functions/search-queries.json").slice(0, 1000),
          deps, options.journal, options.pacing);
      }
      observed = await (options.readStreaks || read)(context);
      const out = summary(observed);
      return {...out, execution: searchOut?.execution || (Object.values(out.business).includes("unknown") ? "failed" : "ok"),
        reason: searchOut?.execution === "failed" ? searchOut.reason : "streaks_readback_finished",
        details: {metrics: out.details.metrics, items: [...out.details.items, ...(searchOut?.details?.items || [])]}};
    });
  } catch (error) {
    require("./telemetry.cjs").failure("stage", error, {capability: "daily_streaks"});
    deps.recordObstacle(error, {capability: "daily_streaks", phase: "readback"});
    return {...summary(observed || []), execution: "failed",
      reason: error.details?.code || "streak_progress_unavailable"};
  }
}
module.exports = {measure, summary, read, run};
