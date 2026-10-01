"use strict";
// Extra activities from the owner's private adapter; goal changes use an exact trusted authorization boundary.
const common = require("./browser_common.cjs");
const { publish } = require("../../common/result.cjs");
const { loadParser } = require("./parser_loader.cjs");
const QUERIES = {
  beautyproducts: [
    "best moisturiser for sensitive skin",
    "haircare products for dry hair",
  ],
  cellphoneplans: ["best cell phone plans", "compare mobile phone plans"],
  cruises: ["Alaska cruise deals", "Caribbean cruise destinations"],
  internetproviders: [
    "internet providers near me",
    "compare home broadband plans",
  ],
  bankaccounts: ["compare checking accounts", "high yield savings accounts"],
  concerttickets: ["concert tickets near me", "upcoming live music concerts"],
  lyrics: ["Shake It Off song lyrics", "Bohemian Rhapsody lyrics"],
  rentalcars: ["car rental deals", "compare airport car rentals"],
};
function kind(offerId) {
  if (typeof offerId !== "string") return null;
  if (offerId === "10XMSRewards_a30081646") return "goal";
  if (/SocialMedia/.test(offerId)) return "social";
  if (/exploreonbing_activation/i.test(offerId)) return "explore";
  return null;
}
function allowed(url, hosts) {
  try {
    const u = new URL(url);
    return (
      u.protocol === "https:" &&
      !u.username &&
      !u.password &&
      (!u.port || u.port === "443") &&
      hosts.includes(u.hostname)
    );
  } catch {
    return false;
  }
}
function plan(offers, metadata) {
  if (
    !Array.isArray(offers) ||
    offers.length > 300 ||
    !Array.isArray(metadata) ||
    metadata.length > 300
  )
    throw Error("inventory_unavailable");
  const ids = new Set();
  for (const offer of offers) {
    if (!offer || typeof offer.offerId !== "string")
      throw Error("inventory_unavailable");
    if (ids.has(offer.offerId)) throw Error("duplicate_offer_inventory");
    ids.add(offer.offerId);
  }
  const meta = new Map();
  for (const row of metadata) {
    if (!row || typeof row.offerId !== "string") continue;
    if (
      meta.has(row.offerId) &&
      meta.get(row.offerId)?.exclusiveLockedFeatureStatus !==
        row.exclusiveLockedFeatureStatus
    )
      meta.set(row.offerId, null);
    else if (!meta.has(row.offerId)) meta.set(row.offerId, row);
  }
  const selected = offers.filter((o) => kind(o.offerId));
  if (selected.length > 30) throw Error("activity_inventory_limit");
  return selected.map((o) => ({
    offerId: o.offerId,
    title: String(o.title || "").slice(0, 300),
    kind: kind(o.offerId),
    status:
      o.isCompleted === true
        ? "complete"
        : o.isLocked === true
          ? "blocked"
          : meta.get(o.offerId)?.exclusiveLockedFeatureStatus === "unlocked"
            ? "eligible"
            : "unknown",
    metadata: meta.get(o.offerId),
  }));
}
async function run(chromium, state, parser, options = {}, deps = common) {
  const business = { social: "unknown", explore: "unknown", goal: "unknown" };
  try {
    return await deps.withBrowser(
      chromium,
      state,
      options,
      async (context, page) => {
        const mainPage = page;
        const verificationPage = await context.newPage();
        async function read(page = mainPage) {
          await page.goto(deps.EARN, {
            waitUntil: "domcontentloaded",
            timeout: 45000,
          });
          await deps.guard(page);
          await page.locator("main").waitFor({ timeout: 20000 });
          await page.waitForTimeout(2500);
          const snapshot = parser.snapshotPage(await deps.boundedHtml(page));
          if (
            !Array.isArray(snapshot.offers) ||
            !snapshot.offers.length ||
            snapshot.offers.length > 300
          )
            throw Error("offer_inventory_unavailable");
          return snapshot.offers;
        }
        async function confirmed(id) {
          for (let i = 0; i < 4; i++) {
            if (
              (await read(verificationPage)).find((o) => o.offerId === id)
                ?.isCompleted === true
            )
              return true;
            await page.waitForTimeout(3000);
          }
          return false;
        }
        let offers = await read();
        const raw = await deps.readFlyout(context);
        if (
          raw?.isError ||
          raw?.userInfo?.isRewardsUser !== true ||
          raw?.flyoutResult?.userStatus?.isRewardsUser !== true
        )
          throw Error("authenticated_inventory_unavailable");
        const flyout = raw.flyoutResult;
        if (
          !Array.isArray(flyout.morePromotions) ||
          !Array.isArray(flyout.exploreOnBingPromotions)
        )
          throw Error("inventory_unavailable");
        const jobs = plan(offers, [
          ...flyout.morePromotions,
          ...flyout.exploreOnBingPromotions,
        ]);
        const outcomes = [];
        for (const job of jobs) {
          if (job.status !== "eligible") {
            outcomes.push({ ...job, status: job.status });
            continue;
          }
          if (job.kind === "goal") {
            if (!options.goal?.url) {
              outcomes.push({ ...job, status: "blocked" });
              continue;
            }
            try {
              const goal = await require("./goal.cjs").setManualGoal(page, {
                ...options.goal,
                guard: deps.guard,
              });
              const complete =
                goal.business.goal === "complete" &&
                (await confirmed(job.offerId));
              outcomes.push({
                ...job,
                status: complete ? "complete" : "unknown",
              });
            } catch (error) {
              error.capability = "goal";
              throw error;
            }
            continue;
          }
          let target, popupPromise;
          try {
            await deps.guard(page);
            if (job.kind === "social") {
              const link = page
                .locator("a")
                .filter({ hasText: job.title })
                .first();
              const href = new URL(await link.getAttribute("href"), page.url())
                .href;
              if (
                !allowed(href, [
                  "www.tiktok.com",
                  "www.youtube.com",
                  "rewards.bing.com",
                ])
              )
                throw Error("unsupported_destination");
              popupPromise = page
                .waitForEvent("popup", { timeout: 15000 })
                .catch(() => null);
              await link.click({ timeout: 15000 });
              target = (await popupPromise) || page;
              await target
                .waitForLoadState("domcontentloaded", { timeout: 20000 })
                .catch(() => {});
              await deps.guard(target);
              await target.waitForTimeout(4000);
            } else {
              const key = Object.keys(QUERIES).find((k) =>
                job.offerId.includes("_" + k + "_"),
              );
              if (!key) {
                outcomes.push({ ...job, status: "unknown" });
                continue;
              }
              const title = job.metadata?.title;
              if (title) {
                const activate = page
                  .locator("button")
                  .filter({ hasText: title })
                  .first();
                if ((await activate.count()) && (await activate.isEnabled())) {
                  await activate.click({ timeout: 15000 });
                  await page.waitForTimeout(3000);
                  await read();
                }
              }
              const entry = page.locator('a[href*="rwAutoFlyout=exb"]').first();
              const href = new URL(await entry.getAttribute("href"), page.url())
                .href;
              if (!allowed(href, ["www.bing.com"]))
                throw Error("unsupported_destination");
              popupPromise = page
                .waitForEvent("popup", { timeout: 15000 })
                .catch(() => null);
              await entry.click({ timeout: 15000 });
              target = (await popupPromise) || page;
              await target
                .waitForLoadState("domcontentloaded", { timeout: 20000 })
                .catch(() => {});
              await deps.guard(target);
              if (new URL(target.url()).hostname !== "www.bing.com")
                throw Error("region_redirect");
              for (const query of QUERIES[key]) {
                await deps.guard(target);
                const box = target.locator("#sb_form_q");
                await box.waitFor({ state: "visible", timeout: 15000 });
                await box.fill(query);
                await box.press("Enter");
                await target
                  .waitForLoadState("domcontentloaded", { timeout: 15000 })
                  .catch(() => {});
                await deps.guard(target);
                await target.waitForTimeout(10000);
                if (await confirmed(job.offerId)) break;
              }
            }
            outcomes.push({
              ...job,
              status: (await confirmed(job.offerId)) ? "complete" : "unknown",
            });
          } catch (error) {
            if (error.message === "human_required") throw error;
            outcomes.push({ ...job, status: "unknown" });
          } finally {
            if (!target && popupPromise) target = await popupPromise;
            if (target && target !== page) await target.close();
          }
          offers = await read();
        }
        for (const key of Object.keys(business)) {
          const rows = outcomes.filter((o) => o.kind === key);
          if (!rows.length) {
            business[key] = "unknown";
            continue;
          }
          if (rows.every((o) => o.status === "complete"))
            business[key] = "complete";
          else if (
            rows.some((o) => o.status === "unknown" || o.status === "eligible")
          )
            business[key] = "unknown";
          else business[key] = "blocked";
        }
        return {
          execution: "ok",
          reason: outcomes.some(
            (o) => o.kind === "goal" && o.status !== "complete",
          )
            ? "goal_requires_manual_action"
            : "extra_readback_finished",
          business,
        };
      },
    );
  } catch (error) {
    common.recordObstacle(error, {
      capability: error.capability === "goal" ? "goal" : "extra",
      phase: "extra_cards",
    });
    return {
      execution: "failed",
      reason: ["human_required", "activity_inventory_limit"].includes(
        error.message,
      )
        ? error.message
        : error.details?.code || "extra_unconfirmed",
      business,
    };
  }
}
async function main() {
  let out;
  try {
    const fs = require("node:fs"),
      path = require("node:path");
    const configFile = path.join(
      process.env.BENEFITS_STATE_DIR,
      "native-config.json",
    );
    const config = fs.existsSync(configFile)
      ? common.boundedJson(configFile, 65536)
      : {};
    out = await run(
      common.dependency(process.env.REWARDS_ROOT),
      common.readState(process.env.BENEFITS_STATE_DIR),
      loadParser(),
      {
        proxy: process.env.REWARDS_PROXY,
        goal: config.goal?.url ? { url: config.goal.url } : undefined,
      },
    );
  } catch (error) {
    out = {
      execution: "failed",
      reason: [
        "upstream_build_not_configured",
        "upstream_build_incompatible",
        "upstream_build_modified",
        "parser_contract_incompatible",
      ].includes(error.message)
        ? error.message
        : "dependency_or_session_unavailable",
      business: { extra: "unknown" },
    };
  }
  publish(out.execution, out.reason, out.business);
}
if (require.main === module) main();
module.exports = { kind, allowed, plan, run, QUERIES };
