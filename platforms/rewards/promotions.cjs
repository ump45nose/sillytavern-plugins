"use strict";
// Narrow adaptation of Rewards v4.3.2 MorePromotions/UrlReward/ClaimBonusPoints.
// GPL-3.0-or-later; source commit and license retained in vendor/rewards-parser.
const common = require("./browser_common.cjs");
const actions = require("./server_actions.cjs");

function eligible(row) {
  return row && row.pointProgressMax > 0 && row.complete !== true &&
    row.exclusiveLockedFeatureStatus !== "locked" &&
    (row.priority >= 0 || row.exclusiveLockedFeatureStatus === "unlocked") &&
    row.attributes?.promotional !== "True";
}
async function run(chromium, state, parser, options, capability) {
  try {
    return await common.withBrowser(chromium, state, options, async (context, page) => {
      async function read() {
        await page.goto(common.EARN, {waitUntil: "domcontentloaded", timeout: 45000});
        await common.guard(page);
        await page.locator("main").waitFor({timeout: 20000});
        await page.waitForTimeout(1500);
        const html = await common.boundedHtml(page);
        const snapshot = parser.snapshotPage(html);
        const raw = common.assertAccountAvailable(await common.readFlyout(context), options.region);
        return {html, snapshot, raw};
      }
      let current = await read();
      if (capability === "claim") {
        const claim = current.raw.flyoutResult.pointClaimCardPromotion;
        if (!claim || claim.complete === true || claim.pointProgressMax === 0)
          return {execution: "ok", reason: "no_pending_bonus", business: {claim: "not_applicable"}};
        const key = "claim_" + options.businessDate;
        if (options.journal.has(key))
          return {execution: "ok", reason: "previous_claim_unconfirmed", business: {claim: "unknown"}};
        const ids = await actions.discover(page, parser, current.html);
        if (!ids.reportClaimAllPoints) throw Error("claim_action_unavailable");
        await options.journal.mark(key, "attempted");
        try {
          await actions.request(page, "/earn", {method: "POST", headers: {
            Accept: "text/x-component", "Content-Type": "text/plain;charset=UTF-8",
            "Next-Action": ids.reportClaimAllPoints,
            "Next-Router-State-Tree": parser.routerStateTree("earn"),
          }, body: "[]"});
        } catch {} // Read back an uncertain request without replaying it.
        current = await read();
        const after = current.raw.flyoutResult.pointClaimCardPromotion;
        const complete = after?.complete === true;
        if (complete) await options.journal.mark(key, "confirmed");
        return {execution: "ok", reason: complete ? "bonus_confirmed" : "bonus_unconfirmed",
          business: {claim: complete ? "complete" : "unknown"}};
      }
      const rows = current.raw.flyoutResult.morePromotions;
      if (!Array.isArray(rows) || rows.length > 300) throw Error("inventory_unavailable");
      const jobs = rows.filter(r => r.pointProgressMax > 0 && (r.complete === true || eligible(r)));
      const results = [];
      const timezoneOffset = await common.timezoneOffset(page, options.timezoneOffset);
      let ids;
      for (const row of jobs.slice(0, 40)) {
        if (row.complete === true) {results.push("complete"); continue;}
        if (!eligible(row)) {results.push("blocked"); continue;}
        const offer = current.snapshot.offers.find(x => x.offerId === row.offerId);
        if (String(row.promotionType).toLowerCase() !== "urlreward" ||
            /exploreonbing/i.test(row.name || "")) {results.push("unknown"); continue;}
        if (!offer?.reportable || !offer.hash || options.journal.has(row.offerId)) {
          results.push(offer?.isCompleted ? "complete" : "unknown"); continue;
        }
        ids ||= await actions.discover(page, parser, current.html);
        if (!ids.reportActivity) throw Error("activity_action_unavailable");
        await options.journal.mark(row.offerId, "attempted");
        try {
          await actions.request(page, "/earn", {method: "POST", headers: {
            Accept: "text/x-component", "Content-Type": "text/plain;charset=UTF-8",
            "Next-Action": ids.reportActivity,
            "Next-Router-State-Tree": parser.routerStateTree("earn"),
          }, body: JSON.stringify([offer.hash, offer.activityType || 11,
            {offerid: row.offerId, isPromotional: offer.isPromotional ? true : "$undefined",
              timezoneOffset}])});
        } catch {}
        let complete = false;
        for (let i = 0; i < 3; i++) {
          await page.waitForTimeout(3000);
          current = await read();
          complete = current.snapshot.offers.find(x => x.offerId === row.offerId)?.isCompleted === true;
          if (complete) break;
        }
        if (complete) await options.journal.mark(row.offerId, "confirmed");
        results.push(complete ? "complete" : "unknown");
      }
      const status = !jobs.length ? "not_applicable" :
        jobs.length > 40 || results.includes("unknown") ? "unknown" :
        results.includes("blocked") ? "blocked" : "complete";
      return {execution: "ok", reason: "promotions_readback_finished",
        business: {more_promotions: status}};
    });
  } catch (error) {
    options.onError?.(error);
    common.recordObstacle(error, {capability, phase: "promotions"});
    return {execution: "failed", reason: error.details?.code ||
      (/^[a-z_]{1,100}$/.test(error.message) ? error.message : "promotions_failed"),
      business: {[capability]: "unknown"}};
  }
}
module.exports = {run, eligible};
