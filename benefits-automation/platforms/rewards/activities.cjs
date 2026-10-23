"use strict";
// Adapted from the owner's private daily-activities.cjs; no upstream full runner.
const common = require("./browser_common.cjs");
const trace = require("./telemetry.cjs");
const interaction = require("./interaction.cjs");
const path = require("node:path");
const { publish } = require("../../common/result.cjs");
const {metric} = require("../../common/details.cjs");
const cycle = require("./daily_cycle.cjs");
const actions = require("./server_actions.cjs");
const {DASHBOARD, progress, section, cards} = require("./daily_page.cjs");
function outcome(complete, reason, observed = null, items = [], cycle) {
  return {
    execution: complete ? "ok" : "failed",
    reason,
    business: { daily: observed?.max === 0 ? "not_applicable" : complete ? "complete" : "unknown" },
    details: {metrics: {daily: metric("count", observed?.current, observed?.max),
      daily_points: metric("points", observed?.points?.current, observed?.points?.max)}, items},
    ...(cycle ? {cycle} : {}),
  };
}
async function run(chromium, storageState, options = {}, deps = common) {
  const pacing = options.pacing || interaction.create(options.interaction);
  let lastProgress = null, lastItems = [], lastCycle;
  try {
    return await deps.withBrowser(
      chromium,
      storageState,
      options,
      async (context, page) => {
        await page.goto(DASHBOARD, {
          waitUntil: "domcontentloaded",
          timeout: 45000,
        });
        await deps.guard(page);
        let after = await progress(page);
        lastProgress = after;
        if (!after) return outcome(false, "daily_progress_unavailable");
        const raw = common.assertAccountAvailable(
          await deps.readFlyout(context),
          options.region,
        );
        const visible = await cards(page);
        const current = cycle.inventory(raw, visible);
        lastCycle = current.date;
        const journal = options.journalForCycle?.(current.date);
        if (!journal) throw Error("daily_journal_unavailable");
        for (const row of current.rows)
          if (!cycle.excluded(row) && row.complete) await journal.mark(row.offerId, "confirmed");
        const scoped = cycle.summary(current.rows);
        after = {current: scoped.current, max: scoped.max, points: scoped.points};
        lastProgress = after;
        const items = [...scoped.items, cycle.item(current.date)];
        lastItems = items;
        if (after.current >= after.max)
          return outcome(true, "daily_already_complete", after, items, current.date);
        let parser, html, offers, timezoneOffset, ids;
        for (const row of current.rows) {
          const redirect = row.activityType === "bingredirect";
          const reportKey = redirect ? row.offerId : "report_" + row.offerId;
          if (cycle.excluded(row) || row.complete) continue;
          if (journal.has(reportKey)) {
            Object.assign(items.find(item => item.id === row.offerId),
              {status: "unknown", reason: "previous_daily_submission_requires_reconciliation"});
            continue;
          }
          if (!redirect && !offers) {
            parser = require("./parser_loader.cjs").loadParser();
            html = await deps.boundedHtml(page);
            offers = parser.snapshotPage(html).offers;
            timezoneOffset = await deps.timezoneOffset(page, options.timezoneOffset);
          }
          const offer = offers?.find(offer => offer.offerId === row.offerId);
          const card = visible.find(card => cycle.matches(row, card));
          const target = cycle.destination(card?.href);
          if (String(row.promotionType).toLowerCase() !== "urlreward" ||
              (redirect ? !target || cycle.excluded({destinationUrl: card?.href})
                : !offer?.reportable || !offer.hash)) {
            Object.assign(items.find(item => item.id === row.offerId),
              {status: "unknown", reason: "daily_action_unavailable"});
            continue;
          }
          let link;
          if (redirect) {
            link = (await section(page)).locator("a").filter({hasText: card.title});
            if ((await link.count()) !== 1 ||
                new URL(await link.getAttribute("href"), DASHBOARD).href !== card.href)
              throw Error("daily_action_unavailable");
          } else {
            ids ||= await actions.discover(page, parser, html);
            if (!ids.reportActivity) throw Error("daily_action_unavailable");
          }
          await deps.guard(page);
          await pacing.pause(page, "action");
          await deps.guard(page);
          await journal.mark(reportKey, "attempted");
          trace.emit("journal.intent", {capability: "daily", offer_ref: trace.reference(row.offerId), state: "attempted"});
          let rejected = false;
          try {
            if (redirect) {
              const opened = page.waitForEvent("popup", {timeout: 15000}).catch(() => null);
              try { await trace.span("activity.submit", {capability: "daily"}, () => link.click({timeout: 10000})); }
              finally {
                const popup = await opened;
                if (popup) {
                  try {
                    await popup.waitForLoadState("domcontentloaded", {timeout: 15000}).catch(() => {});
                    await deps.guard(popup);
                    await pacing.review(popup, 10000);
                  } finally { await popup.close(); }
                }
              }
            } else {
              const response = await actions.reportActivity(page, parser, ids.reportActivity, offer, timezoneOffset);
              rejected = response.accepted === false || response.status >= 400;
            }
          } catch (error) {
            trace.failure("activity.submit", error, {capability: "daily"});
            if (error.details) throw error;
          }
          for (let attempt = 0; attempt < 10; attempt++) {
            await page.goto(DASHBOARD, {
              waitUntil: "domcontentloaded",
              timeout: 45000,
            });
            await deps.guard(page);
            if (!await progress(page)) return outcome(false, "daily_progress_unavailable", null, items, current.date);
            const fresh = cycle.inventory(
              await deps.readFlyout(context), await cards(page));
            const freshSummary = cycle.summary(fresh.rows);
            after = {current: freshSummary.current, max: freshSummary.max, points: freshSummary.points};
            lastProgress = after;
            if (fresh.date !== current.date)
              return outcome(false, "daily_cycle_changed", after, items, fresh.date);
            if (fresh.rows.find(candidate => candidate.offerId === row.offerId)?.complete === true) {
              await journal.mark(reportKey, "confirmed");
              if (reportKey !== row.offerId) await journal.mark(row.offerId, "confirmed");
              Object.assign(items.find(item => item.id === row.offerId), {status: "complete", reason: "fresh_readback"});
              break;
            }
            await page.waitForTimeout(5000);
          }
          if (items.find(x => x.id === row.offerId).status !== "complete")
            Object.assign(items.find(x => x.id === row.offerId), {status: "unknown",
              reason: rejected ? "daily_activity_rejected" : "daily_activity_not_credited"});
          if (after.current >= after.max)
            return outcome(items.every(row => ["complete", "not_applicable"].includes(row.status)), "daily_complete", after, items, current.date);
        }
        return outcome(false, "daily_activity_not_credited", after, items, current.date);
      },
    );
  } catch (error) {
    trace.failure("activity.submit", error);
    common.recordObstacle(error, { capability: "daily", phase: "daily_cards" });
    return {...outcome(
      false,
      error.message === "human_required"
        ? "human_required"
        : error.details?.code || (/^[a-z_]{1,100}$/.test(error.message) ? error.message : "daily_browser_or_network_error"),
      lastProgress, lastItems, lastCycle,
    ), diagnostic: trace.errorFields(error)};
  }
}

async function main() {
  let output;
  try {
    const stateDir = process.env.BENEFITS_STATE_DIR;
    const {readConfig, browserOptions} = require("./runtime_config.cjs");
    output = await run(
      common.dependency(process.env.REWARDS_ROOT),
      common.readState(process.env.BENEFITS_STATE_DIR),
      { ...browserOptions(stateDir, readConfig(stateDir), process.env.REWARDS_PROXY),
        journalForCycle: date => require("./journal.cjs").journal(
          path.join(process.env.BENEFITS_STATE_DIR, "daily-" + date + ".json")) },
    );
  } catch (error) {
    trace.failure("run", error, {capability: "daily"});
    output = outcome(false, "dependency_session_or_browser_unavailable");
  }
  return publish(output.execution, output.reason, output.business, output.details);
}
module.exports = { run };
if (require.main === module)
  main().catch(() => publish("failed", "adapter_error", { daily: "unknown" }));
