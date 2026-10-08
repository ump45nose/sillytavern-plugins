"use strict";
// Extra activities from the owner's private adapter; goal changes use an exact trusted authorization boundary.
const common = require("./browser_common.cjs");
const { publish } = require("../../common/result.cjs");
const { loadParser } = require("./parser_loader.cjs");
const actions = require("./server_actions.cjs");
const QUERIES = {
  // Curated examples from v4.3.2 bing-search-activity-queries.json (GPL-3.0-or-later).
  creditreport: [
    "how to raise credit score quickly",
    "how to improve my credit score",
    "check my credit score for free",
    "what is a good credit score",
    "why did my credit score drop",
    "how to build credit history",
    "free credit report",
    "credit utilisation explained",
    "fastest way to raise credit score",
    "how does credit score work",
  ],
  health: [
    "check symptoms for flu",
    "symptoms of the flu",
    "common cold symptoms in adults",
    "why do I have a headache",
    "symptoms of dehydration",
    "sore throat remedies",
    "symptoms of a sinus infection",
    "food poisoning symptoms and duration",
    "what causes a migraine",
    "signs of low iron",
  ],
  recipe: [
    "how to make pancakes",
    "easy pasta recipe",
    "how to cook salmon",
    "homemade pizza recipe",
    "quick dinner ideas",
    "how to make fried rice",
    "best chocolate chip cookies recipe",
    "vegetarian dinner recipes",
    "how to cook a steak",
    "easy soup recipes",
  ],
  videogames: [
    "video games",
    "favorite video games",
    "cyberpunk 2077",
    "video game",
    "grand theft auto game play learn",
    "Minecraft explained",
    "Halo Infinite review",
    "Forza Horizon 5 review",
    "Starfield review",
    "best Xbox Series X games",
  ],
  dictionary: ["meaning of serendipity", "dictionary definition of resilience"],
  timezonedates: ["time zones around the world", "current time in London"],
  financemarket: ["stock market indices explained", "financial market news"],
  mattress: ["how to choose a mattress", "mattress types compared"],
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
  airportparking: ["airport parking options", "compare airport parking prices"],
  allinclusiveresorts: ["all inclusive resort holidays", "compare all inclusive resorts"],
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
  const now = new Date();
  const today = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
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
      o.isCompleted === true || meta.get(o.offerId)?.complete === true
        ? "complete"
        : o.isLocked === true || (typeof o.date === "string" && o.date > today)
          ? "blocked"
          : ["unlocked", "notsupported"].includes(meta.get(o.offerId)?.exclusiveLockedFeatureStatus)
            ? "eligible"
            : "unknown",
    metadata: meta.get(o.offerId),
  }));
}
async function run(chromium, state, parser, options = {}, deps = common) {
  const business = { social: "unknown", explore: "unknown", goal: "unknown" };
  let confirmedDetails;
  try {
    return await deps.withBrowser(
      chromium,
      state,
      options,
      async (context, page) => {
        const mainPage = page;
        const verificationPage = await context.newPage();
        let currentHtml, actionIds;
        async function read(page = mainPage) {
          await page.goto(deps.EARN, {
            waitUntil: "domcontentloaded",
            timeout: 45000,
          });
          await deps.guard(page);
          await page.locator("main").waitFor({ timeout: 20000 });
          await page.waitForTimeout(2500);
          const html = await deps.boundedHtml(page);
          if (page === mainPage) currentHtml = html;
          const snapshot = parser.snapshotPage(html);
          if (
            !Array.isArray(snapshot.offers) ||
            !snapshot.offers.length ||
            snapshot.offers.length > 300
          )
            throw Error("offer_inventory_unavailable");
          return snapshot.offers;
        }
        async function confirmed(id, explore = false) {
          for (let i = 0; i < 2; i++) {
            if (explore) {
              const raw = common.assertAccountAvailable(await deps.readFlyout(context), options.region);
              const rows = raw.flyoutResult.exploreOnBingPromotions;
              if (!Array.isArray(rows) || rows.length > 300) throw Error("inventory_unavailable");
              const row = rows.find(o => o.offerId === id);
              if (row?.complete === true ||
                  (row?.pointProgressMax > 0 && row.pointProgress >= row.pointProgressMax)) return true;
            } else
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
        common.assertAccountAvailable(raw, options.region);
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
        const outcomes = jobs.map((job) => ({
          ...job,
          status: job.status === "eligible" ? "unknown" : job.status,
          reason: job.status,
        }));
        function saveStatus() {
          if (!process.env.BENEFITS_RESULT_PATH) return;
          const fs = require("node:fs"), path = require("node:path");
          const file = path.join(path.dirname(process.env.BENEFITS_RESULT_PATH), "extra-status.json");
          const safe = outcomes.map(o => ({offer_id: o.offerId, kind: o.kind,
            status: o.status, reason: o.reason, activation: o.activation || "not_requested"}));
          const tmp = file + ".tmp";
          fs.writeFileSync(tmp, JSON.stringify(safe), {mode: 0o600}); fs.renameSync(tmp, file);
        }
        function deliveryDetails() {
          return {metrics: {}, items: outcomes.slice(0,100).map(o => ({
            id: String(o.offerId).slice(0,128),
            name: String(o.title || o.metadata?.title || o.offerId).replace(/[\x00-\x1f]/g, " ").slice(0,200),
            status: o.status, reason: o.reason === "eligible" ? "not_yet_confirmed" : o.reason,
          }))};
        }
        function updateBusiness() {
          for (const key of Object.keys(business)) {
            const rows = outcomes.filter((o) => o.kind === key);
            business[key] = !rows.length
              ? "not_applicable"
              : rows.every((o) => o.status === "complete")
                ? "complete"
                : rows.some((o) => o.status === "unknown")
                  ? "unknown"
                  : "blocked";
          }
        }
        function record(job, status, reason = status === "unknown" ? "offer_not_credited" : status) {
          Object.assign(outcomes.find((o) => o.offerId === job.offerId), {status, reason});
          updateBusiness();
          saveStatus();
          confirmedDetails = deliveryDetails();
        }
        updateBusiness();
        for (const job of jobs) {
          if (job.status !== "eligible") {
            record(job, job.status);
            continue;
          }
          if (job.kind === "goal") {
            if (!options.goal?.url) {
              record(job, "blocked");
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
              record(job, complete ? "complete" : "unknown");
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
                record(job, "unknown", "search_topic_unsupported");
                continue;
              }
              // GPL adaptation of v4.3.2 activateSearchOnBing: use the current
              // offer's hash and dynamically discovered action, not title clicks.
              const offer = offers.find(o => o.offerId === job.offerId);
              if (!offer?.reportable || !offer.hash || !options.journal)
                throw Error("activation_evidence_unavailable");
              if (!options.journal.has(job.offerId)) {
                actionIds ||= await actions.discover(page, parser, currentHtml);
                if (!actionIds.reportActivity) throw Error("activity_action_unavailable");
                await options.journal.mark(job.offerId, "attempted");
                try {
                  const response = await actions.request(page, "/earn", {method: "POST", headers: {
                    Accept: "text/x-component", "Content-Type": "text/plain;charset=UTF-8",
                    "Next-Action": actionIds.reportActivity,
                    "Next-Router-State-Tree": parser.routerStateTree("earn"),
                  }, body: JSON.stringify([offer.hash, 11, {offerid: job.offerId,
                    isPromotional: "$undefined", timezoneOffset: options.timezoneOffset || 0}])});
                  outcomes.find(o => o.offerId === job.offerId).activation =
                    response.status === 200 && /^\d+:true\s*$/m.test(response.text)
                      ? "acknowledged" : "not_acknowledged";
                } catch { outcomes.find(o => o.offerId === job.offerId).activation = "response_lost"; }
              } else {
                outcomes.find(o => o.offerId === job.offerId).activation = "previously_attempted";
              }
              const href = job.metadata?.destinationUrl;
              if (!allowed(href, ["www.bing.com"]))
                throw Error("unsupported_destination");
              target = await context.newPage();
              await target.goto(href, {waitUntil: "domcontentloaded", timeout: 30000});
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
                const queryKey = "query_" + require("node:crypto").createHash("sha256")
                  .update(job.offerId + "\0" + query).digest("hex");
                if (options.journal.has(queryKey)) continue;
                await box.fill(query);
                await options.journal.mark(queryKey, "attempted");
                await box.press("Enter");
                await target
                  .waitForLoadState("domcontentloaded", { timeout: 15000 })
                  .catch(() => {});
                await deps.guard(target);
                await target.waitForTimeout(10000);
                if (await confirmed(job.offerId, true)) break;
              }
            }
            const complete = await confirmed(job.offerId, job.kind === "explore");
            if (complete && job.kind === "explore") await options.journal.mark(job.offerId, "confirmed");
            record(job, complete ? "complete" : "unknown");
          } catch (error) {
            if (error.message === "human_required" || error.details)
              throw error;
            options.onError?.(error);
            record(job, "unknown", /^[a-z_]{1,100}$/.test(error.message)
              ? error.message : "browser_operation_failed");
          } finally {
            if (!target && popupPromise) target = await popupPromise;
            if (target && target !== page) await target.close();
          }
          offers = await read();
        }
        return {
          execution: "ok",
          reason: outcomes.some(
            (o) => o.kind === "goal" && o.status !== "complete",
          )
            ? "goal_requires_manual_action"
            : "extra_readback_finished",
          business,
          details: deliveryDetails(),
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
      details: confirmedDetails,
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
        journal: require("./punchcards.cjs").journal(path.join(process.env.BENEFITS_STATE_DIR,
          "explore-" + process.env.BENEFITS_BUSINESS_DATE + ".json")),
        timezoneOffset: config.timezoneOffset || 0,
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
  publish(out.execution, out.reason, out.business, out.details);
}
if (require.main === module) main();
module.exports = { kind, allowed, plan, run, QUERIES };
