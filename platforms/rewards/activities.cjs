"use strict";
// Adapted from the owner's private daily-activities.cjs; no upstream full runner.
const fs = require("node:fs");
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
async function run(chromium, storageState, { proxy } = {}) {
  let browser, context;
  let output = outcome(false, "daily_activity_unconfirmed");
  try {
    // Do not disable the browser sandbox to make a restricted cloud smoke pass.
    browser = await chromium.launch({
      headless: true,
      chromiumSandbox: true,
      ...(proxy ? { proxy: { server: proxy, bypass: "r.bing.com" } } : {}),
    });
    context = await browser.newContext({ storageState });
    const page = await context.newPage();
    await page.goto(DASHBOARD, {
      waitUntil: "domcontentloaded",
      timeout: 45000,
    });
    let after = await progress(page);
    if (!after) return outcome(false, "daily_progress_unavailable");
    if (after.current >= after.max)
      return outcome(true, "daily_already_complete");
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
        await link.click({ timeout: 15000 });
        popup = await popupPromise;
        if (popup) {
          await popup
            .waitForLoadState("domcontentloaded", { timeout: 30000 })
            .catch(() => {});
          await popup.waitForTimeout(10000);
        }
        for (let i = 0; i < 10; i++) {
          await page.goto(DASHBOARD, {
            waitUntil: "domcontentloaded",
            timeout: 45000,
          });
          after = await progress(page);
          if (!after) return outcome(false, "daily_progress_unavailable");
          if (after.current > previous) break;
          await page.waitForTimeout(5000);
        }
      } finally {
        popup = popup || (await popupPromise);
        if (popup) await popup.close();
      }
      if (after.current >= after.max) return outcome(true, "daily_complete");
    }
    output = outcome(false, "daily_activity_not_credited");
  } catch {
    // Do not leak provider exception URLs or account state in public results.
    output = outcome(false, "daily_browser_or_network_error");
  } finally {
    // Close all contexts/pages, including a popup created after a click timeout.
    try {
      if (context) await context.close();
    } finally {
      if (browser) await browser.close();
    }
  }
  return output;
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
    const root = process.env.REWARDS_ROOT;
    if (!root || !path.isAbsolute(root)) throw Error("dependency_unavailable");
    const packageFile = path.join(root, "node_modules/patchright/package.json");
    const pkg = JSON.parse(fs.readFileSync(packageFile, "utf8"));
    if (pkg.version !== "1.61.1") throw Error("dependency_incompatible");
    const statePath = path.join(
      process.env.BENEFITS_STATE_DIR,
      "storage-state.json",
    );
    const fd = fs.openSync(statePath, "r");
    let state;
    try {
      const bytes = Buffer.alloc(1024 * 1024 + 1);
      const size = fs.readSync(fd, bytes, 0, bytes.length, 0);
      if (size > 1024 * 1024) throw Error("invalid_session");
      state = JSON.parse(bytes.subarray(0, size));
      if (
        !state ||
        !Array.isArray(state.cookies) ||
        !Array.isArray(state.origins)
      )
        throw Error("invalid_session");
    } finally {
      fs.closeSync(fd);
    }
    const { chromium } = require(path.join(root, "node_modules/patchright"));
    output = await run(chromium, state, { proxy: process.env.REWARDS_PROXY });
  } catch {
    output = outcome(false, "dependency_session_or_browser_unavailable");
  }
  return publish(output.execution, output.reason, output.business);
}
module.exports = { parseProgress, allowedCard, run, loadState };
if (require.main === module)
  main().catch(() => publish("failed", "adapter_error", { daily: "unknown" }));
