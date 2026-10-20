"use strict";
// Adapted from the owner's private daily-activities.cjs; no upstream full runner.
const common = require("./browser_common.cjs");
const trace = require("./telemetry.cjs");
const interaction = require("./interaction.cjs");
const path = require("node:path");
const { publish } = require("../../common/result.cjs");
const {metric} = require("../../common/details.cjs");
const quiz = require("./daily_quiz.cjs");
const LABEL = /^(Daily activit(?:y|ies)|Daily Set|每日活动|每日活動|每日設定)$/i;
const DASHBOARD = "https://rewards.bing.com/dashboard";
const DAILY_SELECTOR = '[role="progressbar"][aria-label="Daily Set" i],'+
  '[role="progressbar"][aria-label="Daily activities" i],'+
  '[role="progressbar"][aria-label="Daily activity" i],'+
  '[role="progressbar"][aria-label="每日活动"],'+
  '[role="progressbar"][aria-label="每日活動"],'+
  '[role="progressbar"][aria-label="每日設定"]';
const HOSTS = new Set([
  "www.bing.com",
  "cn.bing.com",
  "bing.com",
  "rewards.bing.com",
]);
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
function allowedCard(href) {
  try {
    const u = new URL(href);
    return (
      u.protocol === "https:" &&
      !u.username &&
      !u.password &&
      (!u.port || u.port === "443") &&
      HOSTS.has(u.hostname)
    );
  } catch {
    return false;
  }
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
    business: { daily: complete ? "complete" : "unknown" },
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
        const current = require("./daily_cycle.cjs").inventory(raw, visible);
        lastCycle = current.date;
        const journal = options.journalForCycle?.(current.date);
        for (const row of current.rows)
          if (row.complete) await journal?.mark(row.offerId, "confirmed");
        const items = current.rows.map(row => ({id: row.offerId, name: row.title,
          status: row.complete ? "complete" : "incomplete", reason: "fresh_readback"}));
        items.push(require("./daily_cycle.cjs").item(current.date));
        lastItems = items;
        if (after.current >= after.max)
          return outcome(true, "daily_already_complete", after, items, current.date);
        for (const row of current.rows) {
          const card = visible.find(card => require("./daily_cycle.cjs").matches(row, card));
          if (row.complete) continue;
          const resumeQuiz = journal?.has(row.offerId) && quiz.destination(card.href, row.offerId);
          if (journal?.has(row.offerId) && !resumeQuiz) continue;
          if (!allowedCard(card.href)) continue;
          await deps.guard(page);
          const currentPanel = await section(page);
          const link = currentPanel
            .locator("a")
            .filter({ hasText: card.title })
            .first();
          if (/已完成|Completed/i.test(await link.innerText())) continue;
          let popup;
          const popupPromise = resumeQuiz ? Promise.resolve(null) : page
            .waitForEvent("popup", { timeout: 15000 })
            .catch(() => null);
          try {
            if (resumeQuiz) {
              // Reopen the current task's destination to continue unanswered quiz
              // steps; do not click its already-attempted dashboard card again.
              popup = await context.newPage();
              await popup.goto(card.href, {waitUntil: "domcontentloaded", timeout: 45000});
            } else {
              // Once per visible card. A timeout does not trigger another click.
              await deps.guard(page);
              await pacing.pause(page, "action");
              await deps.guard(page);
              await journal?.mark(row.offerId, "attempted");
              trace.emit("journal.intent", {capability: "daily", offer_ref: trace.reference(row.offerId), state: "attempted"});
              await trace.span("activity.click", {offer_ref: trace.reference(card.href)}, () =>
                link.click({ timeout: 15000, delay: 120 }));
              popup = await popupPromise;
            }
            if (popup) {
              await popup
                .waitForLoadState("domcontentloaded", { timeout: 30000 })
                .catch(() => {});
              await deps.guard(popup);
              await pacing.review(popup, 10000);
              if (quiz.destination(card.href, row.offerId))
                await quiz.finish(popup, row, {journal, guard: deps.guard, pacing,
                  confirmed: async () => {
                    const raw = common.assertAccountAvailable(await deps.readFlyout(context), options.region);
                    return Object.values(raw.flyoutResult.dailySetPromotions)
                      .flat().some(x => x.offerId === row.offerId && x.complete === true);
                  }});
            }
            for (let i = 0; i < 10; i++) {
              await page.goto(DASHBOARD, {
                waitUntil: "domcontentloaded",
                timeout: 45000,
              });
              await deps.guard(page);
              after = await progress(page);
              lastProgress = after;
              if (!after) return outcome(false, "daily_progress_unavailable", null, items, current.date);
              const fresh = require("./daily_cycle.cjs").inventory(
                await deps.readFlyout(context), await cards(page));
              if (fresh.date !== current.date)
                return outcome(false, "daily_cycle_changed", after, items, fresh.date);
              if (fresh.rows.find(x => x.offerId === row.offerId)?.complete === true) {
                await journal?.mark(row.offerId, "confirmed");
                Object.assign(items.find(x => x.id === row.offerId), {status: "complete", reason: "fresh_readback"});
                break;
              }
              await page.waitForTimeout(5000);
            }
          } finally {
            popup = popup || (await popupPromise);
            if (popup) await popup.close();
          }
          if (items.find(x => x.id === row.offerId).status !== "complete")
            Object.assign(items.find(x => x.id === row.offerId), {status: "unknown", reason: "daily_activity_not_credited"});
          if (after.current >= after.max)
            return outcome(items.filter(x => x.id !== "rewards_cycle_" + current.date).every(x => x.status === "complete"), "daily_complete", after, items, current.date);
        }
        return outcome(false, "daily_activity_not_credited", after, items, current.date);
      },
    );
  } catch (error) {
    trace.failure("activity.click", error);
    common.recordObstacle(error, { capability: "daily", phase: "daily_cards" });
    return {...outcome(
      false,
      error.message === "human_required"
        ? "human_required"
        : error.details?.code || "daily_browser_or_network_error",
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
module.exports = { parseProgress, progress, cards, allowedCard, run, loadState };
if (require.main === module)
  main().catch(() => publish("failed", "adapter_error", { daily: "unknown" }));
