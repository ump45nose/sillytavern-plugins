"use strict";
// Source and MIT attribution retained in upstream/laowang-checkin.
const path = require("node:path");
const { publish } = require("../../common/result.cjs");
async function run(firefox, profile, { proxy, statusOnly = false } = {}) {
  let context;
  try {
    context = await firefox.launchPersistentContext(profile, {
      headless: true,
      ...(proxy ? { proxy: { server: proxy } } : {}),
      viewport: { width: 1280, height: 800 },
    });
    const page = context.pages()[0] || (await context.newPage());
    const url = "https://laowang.vip/plugin.php?id=k_misign:sign";
    await page.goto(url, { waitUntil: "domcontentloaded", timeout: 45000 });
    await page.waitForTimeout(1000);
    const signed = async () =>
      (await page.locator(".qdleft .btnvisted").count()) > 0;
    if (await signed())
      return { execution: "ok", reason: "already_signed", checkin: "complete" };
    if (await page.locator("#tncode").count())
      return {
        execution: "failed",
        reason: "human_required",
        checkin: "blocked",
      };
    if (statusOnly)
      return { execution: "ok", reason: "not_signed", checkin: "incomplete" };
    const html = await page.content(),
      hash = html.match(/formhash=([a-f0-9]{8})/);
    if (!hash)
      return {
        execution: "failed",
        reason: "authentication_unconfirmed",
        checkin: "blocked",
      };
    await page.goto(
      url + "&operation=qiandao&formhash=" + hash[1] + "&format=empty",
      { waitUntil: "domcontentloaded", timeout: 45000 },
    );
    if (await page.locator("#tncode").count())
      return {
        execution: "failed",
        reason: "human_required",
        checkin: "blocked",
      };
    await page.goto(url, { waitUntil: "domcontentloaded", timeout: 45000 });
    const confirmed = await signed();
    return {
      execution: confirmed ? "ok" : "failed",
      reason: confirmed ? "sign_confirmed" : "business_unconfirmed",
      checkin: confirmed ? "complete" : "unknown",
    };
  } catch {
    return {
      execution: "failed",
      reason: "browser_or_network_error",
      checkin: "unknown",
    };
  } finally {
    if (context) await context.close();
  }
}
async function login(firefox, profile, proxy) {
  let context;
  try {
    if (!process.stdin.isTTY)
      return {
        execution: "failed",
        reason: "interactive_terminal_required",
        checkin: "unknown",
      };
    context = await firefox.launchPersistentContext(profile, {
      headless: false,
      ...(proxy ? { proxy: { server: proxy } } : {}),
    });
    const page = context.pages()[0] || (await context.newPage());
    await page.goto("https://laowang.vip/forum.php", {
      waitUntil: "domcontentloaded",
      timeout: 45000,
    });
    const input = require("node:readline/promises").createInterface({
      input: process.stdin,
      output: process.stdout,
    });
    try {
      await input.question("Complete login manually, then press Enter.");
    } finally {
      input.close();
    }
    return {
      execution: "ok",
      reason: "manual_login_closed_unverified",
      checkin: "unknown",
    };
  } finally {
    if (context) await context.close();
  }
}
async function main() {
  let firefox;
  try {
    const version = require("playwright-firefox/package.json").version;
    if (version !== "1.63.0") throw Error("version");
    firefox = require("playwright-firefox").firefox;
  } catch {
    return publish("failed", "dependency_unavailable_or_incompatible", {
      checkin: "unknown",
      reward: "unknown",
    });
  }
  let r;
  try {
    if (process.argv.includes("--login"))
      r = await login(
        firefox,
        path.join(process.env.BENEFITS_STATE_DIR, "browser"),
        process.env.LAOWANG_PROXY,
      );
    else
      r = await run(
        firefox,
        path.join(process.env.BENEFITS_STATE_DIR, "browser"),
        {
          proxy: process.env.LAOWANG_PROXY,
          statusOnly: process.argv.includes("--status"),
        },
      );
  } catch {
    r = {
      execution: "failed",
      reason: "browser_cleanup_failed",
      checkin: "unknown",
    };
  }
  publish(r.execution, r.reason, { checkin: r.checkin, reward: "unknown" });
}
if (require.main === module) main();
module.exports = { run };
