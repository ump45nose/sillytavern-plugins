"use strict";
// Compact read-only replacement for the GPL snapshot source retained in upstream/.
const { publish } = require("../../common/result.cjs");
const common = require("./browser_common.cjs");
const trace = require("./telemetry.cjs");
const { parseProgress, progress, cards } = require("./activities.cjs");
const {metric, number} = require("../../common/details.cjs");
function details(raw, daily, app) {
  const {quota, quotas} = require("./search.cjs");
  const flyout = raw.flyoutResult, metrics = {}, items = [];
  const put = (key, q) => { metrics[key] = metric("points", q.earned, q.max); };
  for (const [key, q] of Object.entries(quotas(raw, "desktop"))) put(key, q);
  const counters = flyout.userStatus.counters;
  if (counters.MobileSearch || counters.mobileSearch)
    put("mobile_search", quota(counters.MobileSearch ?? counters.mobileSearch));
  metrics.daily = metric("count", daily?.current, daily?.max);
  metrics.app_daily = metric("count", app?.current, app?.max);
  metrics.balance = metric("points", flyout.userStatus.availablePoints);
  let locked = 0, omitted = 0;
  for (const [key, rows] of [["explore", flyout.exploreOnBingPromotions],
      ["more_promotions", flyout.morePromotions]]) {
    if (!Array.isArray(rows) || rows.length > 300) { put(key, quota(null)); continue; }
    const pointRows = rows.filter(x => number(x?.pointProgressMax) > 0);
    const currentRows = key === "more_promotions" ? applicable(pointRows) : pointRows;
    const eligible = currentRows.filter(x => x.complete === true || x.isCompleted === true ||
      ["unlocked", "notsupported"].includes(x.exclusiveLockedFeatureStatus));
    const known = currentRows.every(x => x.complete === true || x.isCompleted === true ||
      ["unlocked", "notsupported", "locked"].includes(x.exclusiveLockedFeatureStatus));
    put(key, quota(known ? eligible : null));
    for (const [i, x] of pointRows.entries()) {
      const unassigned = key === "more_promotions" && !currentRows.includes(x);
      const status = unassigned ? "not_applicable" : group([x], {requireEligibility: true});
      locked += status === "blocked" ? 1 : 0;
      if (items.length >= 100) { omitted++; continue; }
      items.push({id: String(x.offerId || key + "_" + i).slice(0,128),
        name: String(x.title || x.name || key).replace(/[\x00-\x1f]/g, " ").slice(0,200),
        status, reason: unassigned ? "platform_ineligible" : status === "blocked" ? "platform_locked" : "fresh_readback"});
    }
  }
  metrics.locked_tasks = metric("count", locked);
  metrics.omitted_items = metric("count", omitted);
  return {metrics, items};
}
function applicable(rows) {
  return rows.filter(row => row.complete === true || row.isCompleted === true ||
    !(row.exclusiveLockedFeatureStatus === "locked" || row.attributes?.promotional === "True" ||
      (Number.isFinite(row.priority) && row.priority < 0 && row.exclusiveLockedFeatureStatus !== "unlocked")));
}
function counter(current, max) {
  const p = parseProgress(String(current ?? ""), String(max ?? ""));
  return p ? (p.current >= p.max ? "complete" : "incomplete") : "unknown";
}
function group(items, { requireEligibility = false } = {}) {
  if (!Array.isArray(items)) return "unknown";
  if (items.length === 0) return "not_applicable";
  if (items.length > 300) return "unknown";
  const states = items.map((x) => {
    if (!x || typeof x !== "object") return "unknown";
    if (x.complete === true || x.isCompleted === true) return "complete";
    if (
      x.exclusiveLockedFeatureStatus === "locked"
    )
      return "blocked";
    // Explicit counter progress is enough for counter records, but offer eligibility is separate.
    if (
      (requireEligibility || "exclusiveLockedFeatureStatus" in x) &&
      !["unlocked", "notsupported"].includes(x.exclusiveLockedFeatureStatus)
    )
      return "unknown";
    return counter(x.pointProgress, x.pointProgressMax);
  });
  for (const state of ["unknown", "incomplete", "blocked"])
    if (states.includes(state)) return state;
  return "complete";
}
function summarize(raw, daily, region = null) {
  common.assertAccountAvailable(raw, region);
  const flyout = raw.flyoutResult,
    counters = flyout.userStatus.counters;
  if (!counters || typeof counters !== "object")
    throw Error("counter_inventory_unavailable");
  return {
    daily: daily ? counter(daily.current, daily.max) : "unknown",
    desktop_search: group(counters.PCSearch ?? counters.pcSearch),
    mobile_search: group(counters.MobileSearch ?? counters.mobileSearch),
    explore: group(flyout.exploreOnBingPromotions, {
      requireEligibility: true,
    }),
    promotions: group(Array.isArray(flyout.morePromotions) ? applicable(flyout.morePromotions) : flyout.morePromotions,
      { requireEligibility: true }),
  };
}
async function run(chromium, state, options = {}, deps = common) {
  try {
    return await deps.withBrowser(
      chromium,
      state,
      options,
      async (context, page) => {
        await page.goto(deps.DASHBOARD, {
          waitUntil: "domcontentloaded",
          timeout: 45000,
        });
        await deps.guard(page);
        const daily = await progress(page);
        const raw = await deps.readFlyout(context);
        const business = summarize(raw, daily, options.region);
        const app = await page.evaluate(() => {
          const rows = [...document.querySelectorAll('[role="progressbar"]')]
            .filter(x => /^(Mobile App|移动应用|行動裝置應用程式)$/i.test(x.getAttribute('aria-label') || ''));
          return rows.length === 1 ? {current: rows[0].getAttribute('aria-valuenow'),
            max: rows[0].getAttribute('aria-valuemax')} : null;
        });
        business.app_daily = app ? counter(app.current, app.max) : "unknown";
        const current = require("./daily_cycle.cjs").inventory(raw, await cards(page)), cycle = current.date;
        const streaks = require("./streaks.cjs").summary(
          require("./parser_loader.cjs").loadParser().snapshotPage(await deps.boundedHtml(page)).streaks);
        const observed = details(raw, daily, app);
        return { execution: "ok", reason: "fresh_readonly_snapshot", cycle,
          business: {...business, ...streaks.business},
          details: {metrics: {...observed.metrics, ...streaks.details.metrics},
            items: [...observed.items, ...current.rows.map(row => ({id: row.offerId, name: row.title,
              status: row.complete ? "complete" : "incomplete", reason: "fresh_readback"})),
              ...streaks.details.items, require("./daily_cycle.cjs").item(cycle)]} };
      },
    );
  } catch (error) {
    trace.failure("snapshot", error);
    common.recordObstacle(error, { capability: "snapshot", phase: "readback" });
    return {
      execution: "failed",
      reason:
        error.message === "human_required"
          ? "human_required"
          : error.details?.code || "snapshot_unavailable",
      business: {
        daily: "unknown",
        desktop_search: "unknown",
        mobile_search: "unknown",
        explore: "unknown",
        promotions: "unknown",
      },
    };
  }
}
async function main() {
  let out;
  try {
    out = await run(
      common.dependency(process.env.REWARDS_ROOT),
      common.readState(process.env.BENEFITS_STATE_DIR),
      { proxy: process.env.REWARDS_PROXY },
    );
  } catch (error) {
    trace.failure("run", error, {capability: "snapshot"});
    out = {
      execution: "failed",
      reason: "dependency_or_session_unavailable",
      business: { snapshot: "unknown" },
    };
  }
  publish(out.execution, out.reason, out.business, out.details);
}
if (require.main === module) main();
module.exports = { run, counter, group, summarize, details };
