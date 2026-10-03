"use strict";
// Source and MIT attribution retained in upstream/laowang-checkin.
const path = require("node:path");
const { publish } = require("../../common/result.cjs");
const challenge = require("./challenge.cjs");
const { createIntent } = require("./intent.cjs");
const URL = "https://laowang.vip/plugin.php?id=k_misign:sign";
async function readStatus(page) {
  const signed = (await page.locator(".qdleft .btnvisted").count()) > 0;
  const details = {};
  for (const [key, selector] of [
    ["reward", "#lxreward"],
    ["streak", "#lxdays"],
    ["days", "#lxtdays"],
  ]) {
    try {
      const text = await page.locator(selector).first().inputValue();
      const number =
        typeof text === "string" && /^\d{1,9}(?:\.\d{1,2})?$/.test(text)
          ? Number(text)
          : null;
      details[key] = number;
    } catch {
      details[key] = null;
    }
  }
  return { signed, details };
}
async function run(
  firefox,
  profile,
  {
    proxy,
    statusOnly = false,
    authorize,
    challengeOptions = {},
    intent = null,
  } = {},
) {
  let context;
  try {
    context = await firefox.launchPersistentContext(profile, {
      headless: true,
      ...(proxy ? { proxy: { server: proxy } } : {}),
      viewport: { width: 1280, height: 800 },
    });
    const page = context.pages()[0] || (await context.newPage());
    await page.goto(URL, { waitUntil: "domcontentloaded", timeout: 45000 });
    challenge.safeTarget(page);
    await page.waitForTimeout(1000);
    let status = await readStatus(page);
    const result = (complete, reason) => ({
      execution: complete ? "ok" : "failed",
      reason,
      checkin: complete ? "complete" : "unknown",
      details: status.details,
    });
    if (status.signed) return result(true, "already_signed");
    if (statusOnly)
      return {
        execution: "ok",
        reason: "not_signed",
        checkin: "incomplete",
        details: status.details,
      };
    if (!intent || typeof intent.mark !== "function") {
      if (
        (await page.locator("#tncode").count()) > 0 &&
        typeof authorize !== "function"
      )
        throw new challenge.PendingChallenge(
          await challenge.observe(
            page,
            "tncode_open",
            challengeOptions.readEvidence,
          ),
        );
      return result(false, "sign_intent_required");
    }
    // A prior uncertain request/submit only permits readback, never blind replay.
    async function verify() {
      const verification = context.newPage ? await context.newPage() : page;
      try {
        for (let i = 0; i < 3; i++) {
          try {
            await verification.goto(URL, {
              waitUntil: "domcontentloaded",
              timeout: 20000,
            });
            challenge.safeTarget(verification);
            status = await readStatus(verification);
            if (status.signed) return true;
          } catch {}
          if (i < 2) await page.waitForTimeout(1500);
        }
        return false;
      } finally {
        if (verification !== page) await verification.close();
      }
    }
    const hasChallenge = async () =>
      (await page.locator("#tncode").count()) > 0;
    if (intent.phase !== "idle") {
      const confirmed = await verify();
      if (confirmed) return result(true, "previous_sign_reconciled");
      const resumable =
        ["challenge_pending", "captcha_rejected"].includes(intent.phase) &&
        intent.attempts < 2 &&
        (await hasChallenge()) &&
        (await page.locator("#submit-btn").count()) === 1 &&
        (await page.locator('input[type="password"]').count()) === 0;
      if (!resumable)
        return result(false, "previous_sign_action_requires_reconciliation");
      // The server still exposes an actual challenge form. Fresh authorization
      // may continue it, without repeating the earlier qiandao request.
    }
    if (!(await hasChallenge())) {
      // Limit HTML before transfer. No page body is saved or logged.
      const html = page.evaluate
        ? await page.evaluate(() => {
            const value = document.documentElement.outerHTML;
            if (value.length > 262144) throw Error("page_too_large");
            return value;
          })
        : await page.content();
      const hash = html.match(/formhash=([a-f0-9]{8})/);
      if (!hash)
        return {
          execution: "failed",
          reason: "authentication_unconfirmed",
          checkin: "blocked",
          details: status.details,
        };
      intent.mark("request_attempted");
      try {
        await page.goto(
          URL + "&operation=qiandao&formhash=" + hash[1] + "&format=empty",
          { waitUntil: "domcontentloaded", timeout: 45000 },
        );
        challenge.safeTarget(page);
      } catch {
        return result(await verify(), "sign_request_reconciled");
      }
    }
    if (await hasChallenge()) {
      intent.mark("challenge_pending");
      const solved = await challenge.solve(page, {
        ...challengeOptions,
        authorize,
        beforeDrag: async () => intent.mark("captcha_attempted"),
        onOutcome: async (status) => {
          if (status === "accepted") intent.mark("captcha_accepted");
          if (status === "rejected") intent.mark("captcha_rejected");
        },
      });
      if (solved.status !== "accepted")
        return result(false, solved.reason || "captcha_unconfirmed");
      // Solver ACK is not sign-in success. Reconcile before a changing click.
      if (await verify())
        return result(true, "sign_reconciled_after_challenge");
      challenge.safeTarget(page);
      const button = page.locator("#submit-btn");
      if ((await button.count()) !== 1)
        return result(false, "sign_control_ambiguous");
      intent.mark("submit_attempted");
      try {
        await button.click({ timeout: 15000 });
      } catch {} // May have reached the server.
    }
    const confirmed = await verify();
    return result(
      confirmed,
      confirmed ? "sign_confirmed" : "business_unconfirmed",
    );
  } catch (error) {
    challenge.record(error);
    return {
      execution: "failed",
      reason:
        error instanceof challenge.PendingChallenge
          ? "human_required"
          : [
                "puzzle_confidence_low",
                "puzzle_samples_insufficient",
                "puzzle_dimensions_invalid",
                "unexpected_origin",
                "origin_unavailable",
              ].includes(error.message)
            ? error.message
            : "browser_or_network_error",
      checkin:
        error instanceof challenge.PendingChallenge ? "blocked" : "unknown",
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
          intent: process.argv.includes("--status")
            ? null
            : createIntent(
                path.join(process.env.BENEFITS_STATE_DIR, "sign-intent.json"),
                process.env.BENEFITS_BUSINESS_DATE,
              ),
        },
      );
  } catch {
    r = {
      execution: "failed",
      reason: "browser_cleanup_failed",
      checkin: "unknown",
    };
  }
  if (r.details) {
    const fs = require("node:fs");
    const file = path.join(
      path.dirname(process.env.BENEFITS_RESULT_PATH),
      "laowang-status.json",
    );
    fs.writeFileSync(file, JSON.stringify(r.details), { mode: 0o600 });
  }
  publish(r.execution, r.reason, { checkin: r.checkin, reward: "unknown" });
}
if (require.main === module) main();
module.exports = { run, readStatus };
