"use strict";
// Adapted from the owner's private daily-activities.cjs; no upstream full runner.
const common = require("./browser_common.cjs");
const path = require("node:path");
const { publish } = require("../../common/result.cjs");
const LABEL = /^(Daily activit(?:y|ies)|Daily Set|每日活动)$/i;
const DASHBOARD = "https://rewards.bing.com/dashboard";
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
  const bar = page.getByRole("progressbar", { name: LABEL });
  await bar.waitFor({ state: "attached", timeout: 20000 });
  return parseProgress(
    await bar.getAttribute("aria-valuenow"),
    await bar.getAttribute("aria-valuemax"),
  );
}
async function section(page) {
  const control = page.getByRole("button", { name: LABEL, exact: true });
  if ((await control.getAttribute("aria-expanded")) === "false")
    await control.click();
  return control.locator("xpath=ancestor::section[1]");
}
function outcome(complete, reason) {
  return {
    execution: complete ? "ok" : "failed",
    reason,
    business: { daily: complete ? "complete" : "unknown" },
  };
}
async function run(chromium, storageState, options = {}, deps = common) {
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
        if (!after) return outcome(false, "daily_progress_unavailable");
        if (after.current >= after.max)
          return outcome(true, "daily_already_complete");
        common.assertAccountAvailable(
          await deps.readFlyout(context),
          options.region,
        );
        const panel = await section(page);
        const cards = await panel.locator("a").evaluateAll((xs) =>
          xs
            .slice(0, 100)
            .map((x) => ({
              title: x.innerText.split("\n")[0].trim().slice(0, 300),
              text: x.innerText.slice(0, 1000),
              href: x.href,
            }))
            .filter((x) => x.title && !/已完成|Completed/i.test(x.text)),
        );
        // Never let malformed task counts turn into an unbounded work loop.
        for (const card of cards.slice(0, Math.min(20, Math.ceil(after.max)))) {
          if (!allowedCard(card.href)) continue;
          await deps.guard(page);
          const currentPanel = await section(page);
          const link = currentPanel
            .locator("a")
            .filter({ hasText: card.title })
            .first();
          if (/已完成|Completed/i.test(await link.innerText())) continue;
          const previous = after.current;
          let popup;
          const popupPromise = page
            .waitForEvent("popup", { timeout: 15000 })
            .catch(() => null);
          try {
            // Once per visible card. A timeout does not trigger another click.
            await deps.guard(page);
            await link.click({ timeout: 15000 });
            popup = await popupPromise;
            if (popup) {
              await popup
                .waitForLoadState("domcontentloaded", { timeout: 30000 })
                .catch(() => {});
              await deps.guard(popup);
              await popup.waitForTimeout(10000);
            }
            for (let i = 0; i < 10; i++) {
              await page.goto(DASHBOARD, {
                waitUntil: "domcontentloaded",
                timeout: 45000,
              });
              await deps.guard(page);
              after = await progress(page);
              if (!after) return outcome(false, "daily_progress_unavailable");
              if (after.current > previous) break;
              await page.waitForTimeout(5000);
            }
          } finally {
            popup = popup || (await popupPromise);
            if (popup) await popup.close();
          }
          if (after.current >= after.max)
            return outcome(true, "daily_complete");
        }
        return outcome(false, "daily_activity_not_credited");
      },
    );
  } catch (error) {
    common.recordObstacle(error, { capability: "daily", phase: "daily_cards" });
    return outcome(
      false,
      error.message === "human_required"
        ? "human_required"
        : error.details?.code || "daily_browser_or_network_error",
    );
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
      { proxy: process.env.REWARDS_PROXY },
    );
  } catch {
    output = outcome(false, "dependency_session_or_browser_unavailable");
  }
  return publish(output.execution, output.reason, output.business);
}
module.exports = { parseProgress, allowedCard, run, loadState };
if (require.main === module)
  main().catch(() => publish("failed", "adapter_error", { daily: "unknown" }));
