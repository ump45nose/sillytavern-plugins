"use strict";
// Compact read-only replacement for the GPL snapshot source retained in upstream/.
const { publish } = require("../../common/result.cjs");
const common = require("./browser_common.cjs");
const { parseProgress, progress } = require("./activities.cjs");
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
    promotions: group(flyout.morePromotions, { requireEligibility: true }),
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
            .filter(x => /^(Mobile App|移动应用)$/i.test(x.getAttribute('aria-label') || ''));
          return rows.length === 1 ? {current: rows[0].getAttribute('aria-valuenow'),
            max: rows[0].getAttribute('aria-valuemax')} : null;
        });
        business.app_daily = app ? counter(app.current, app.max) : "unknown";
        return { execution: "ok", reason: "fresh_readonly_snapshot", business };
      },
    );
  } catch (error) {
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
  } catch {
    out = {
      execution: "failed",
      reason: "dependency_or_session_unavailable",
      business: { snapshot: "unknown" },
    };
  }
  publish(out.execution, out.reason, out.business);
}
if (require.main === module) main();
module.exports = { run, counter, group, summarize };
