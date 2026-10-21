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
const LABEL = /^(Daily activit(?:y|ies)|Daily Set|每日活动|每日活動|每日設定)$/i;
const DASHBOARD = "https://rewards.bing.com/dashboard";
const DAILY_SELECTOR = '[role="progressbar"][aria-label="Daily Set" i],'+
  '[role="progressbar"][aria-label="Daily activities" i],'+
  '[role="progressbar"][aria-label="Daily activity" i],'+
  '[role="progressbar"][aria-label="每日活动"],'+
  '[role="progressbar"][aria-label="每日活動"],'+
  '[role="progressbar"][aria-label="每日設定"]';
function parseProgress(current, max) {
  if (
    typeof current !== "string" ||
    typeof max !== "string" ||
    !current.trim() ||
    !max.trim()
  )
    return null;
  const c = Number(current),
    m = Number(max);
  if (!Number.isFinite(c) || !Number.isFinite(m) || c < 0 || m <= 0)
    return null;
  return { current: c, max: m };
}
async function progress(page) {
  await page.waitForFunction(selector => document.querySelectorAll(selector).length === 1,
    DAILY_SELECTOR, {timeout: 20000});
  const bar = page.locator(DAILY_SELECTOR);
  return parseProgress(
    await bar.getAttribute("aria-valuenow"),
    await bar.getAttribute("aria-valuemax"),
  );
}
async function section(page) {
  const control = page.getByRole("button", { name: LABEL, exact: true });
  if ((await control.getAttribute("aria-expanded")) === "false")
    await control.click();
  await page.waitForTimeout(1000);
  return control.locator("xpath=ancestor::section[1]");
}
async function cards(page) {
  const panel = await section(page);
  return panel.locator("a").evaluateAll(xs => xs.slice(0, 100).map(x => ({
    title: x.innerText.split("\n")[0].trim().slice(0, 300),
    text: x.innerText.slice(0, 1000), href: x.href,
  })).filter(x => x.title));
}
function outcome(complete, reason, observed = null, items = [], cycle) {
  return {
    execution: complete ? "ok" : "failed",
    reason,
    business: { daily: observed?.max === 0 ? "not_applicable" : complete ? "complete" : "unknown" },
    details: {metrics: {daily: metric("count", observed?.current, observed?.max)}, items},
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
        after = {current: scoped.current, max: scoped.max};
        lastProgress = after;
        const items = [...scoped.items, cycle.item(current.date)];
        lastItems = items;
        if (after.current >= after.max)
          return outcome(true, "daily_already_complete", after, items, current.date);
        const parser = require("./parser_loader.cjs").loadParser();
        const html = await deps.boundedHtml(page);
        const offers = parser.snapshotPage(html).offers;
        const timezoneOffset = await deps.timezoneOffset(page, options.timezoneOffset);
        let ids;
        for (const row of current.rows) {
          const reportKey = "report_" + row.offerId;
          if (cycle.excluded(row) || row.complete || journal.has(reportKey)) continue;
          const offer = offers.find(offer => offer.offerId === row.offerId);
          if (String(row.promotionType).toLowerCase() !== "urlreward" ||
              !offer?.reportable || !offer.hash) {
            Object.assign(items.find(item => item.id === row.offerId),
              {status: "unknown", reason: "daily_action_unavailable"});
            continue;
          }
          ids ||= await actions.discover(page, parser, html);
          if (!ids.reportActivity) throw Error("daily_action_unavailable");
          await deps.guard(page);
          await pacing.pause(page, "action");
          await deps.guard(page);
          await journal.mark(reportKey, "attempted");
          trace.emit("journal.intent", {capability: "daily", offer_ref: trace.reference(row.offerId), state: "attempted"});
          try {
            await actions.reportActivity(page, parser, ids.reportActivity, offer, timezoneOffset);
          } catch (error) {
            trace.failure("activity.submit", error, {capability: "daily"});
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
            after = {current: freshSummary.current, max: freshSummary.max};
            lastProgress = after;
            if (fresh.date !== current.date)
              return outcome(false, "daily_cycle_changed", after, items, fresh.date);
            if (fresh.rows.find(candidate => candidate.offerId === row.offerId)?.complete === true) {
              await journal.mark(reportKey, "confirmed");
              await journal.mark(row.offerId, "confirmed");
              Object.assign(items.find(item => item.id === row.offerId), {status: "complete", reason: "fresh_readback"});
              break;
            }
            await page.waitForTimeout(5000);
          }
          if (items.find(x => x.id === row.offerId).status !== "complete")
            Object.assign(items.find(x => x.id === row.offerId), {status: "unknown", reason: "daily_activity_not_credited"});
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

function loadState(dbPath, email) {
  if (!dbPath || !email || !path.isAbsolute(dbPath))
    throw Error("session_unavailable");
  const { DatabaseSync } = require("node:sqlite");
  const db = new DatabaseSync(dbPath, { readOnly: true });
  try {
    const row = db
      .prepare(
        "SELECT storage_state FROM sessions WHERE email=? AND platform=?",
      )
      .get(email, "desktop");
    if (
      !row ||
      typeof row.storage_state !== "string" ||
      Buffer.byteLength(row.storage_state) > 1024 * 1024
    )
      throw Error("session_unavailable");
    const state = JSON.parse(row.storage_state);
    if (
      !state ||
      !Array.isArray(state.cookies) ||
      !Array.isArray(state.origins)
    )
      throw Error("invalid_session");
    return state;
  } finally {
    db.close();
  }
}
async function main() {
  let output;
  try {
    output = await run(
      common.dependency(process.env.REWARDS_ROOT),
      common.readState(process.env.BENEFITS_STATE_DIR),
      { proxy: process.env.REWARDS_PROXY,
        journalForCycle: date => require("./punchcards.cjs").journal(
          path.join(process.env.BENEFITS_STATE_DIR, "daily-" + date + ".json")) },
    );
  } catch (error) {
    trace.failure("run", error, {capability: "daily"});
    output = outcome(false, "dependency_session_or_browser_unavailable");
  }
  return publish(output.execution, output.reason, output.business, output.details);
}
module.exports = { parseProgress, progress, cards, run, loadState };
if (require.main === module)
  main().catch(() => publish("failed", "adapter_error", { daily: "unknown" }));
