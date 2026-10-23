"use strict";
// Adapted protocol logic: TheNetsky/Microsoft-Rewards-Script v4.3.2, GPL-3.0-or-later.
// Full license and exact source commit are retained under vendor/rewards-parser.
const path = require("node:path");
const common = require("./browser_common.cjs"),
  actions = require("./server_actions.cjs");
const trace = require("./telemetry.cjs");
const interaction = require("./interaction.cjs");
const { loadParser } = require("./parser_loader.cjs");
const { publish } = require("../../common/result.cjs");
const PARENT = "WW_pcparent_redesign_existinguser_onboarding_offer_punchcard";
function classify(child, metadata, autoClaim = false) {
  if (child?.isCompleted === true || metadata?.complete === true)
    return "complete";
  if (!metadata || metadata.exclusiveLockedFeatureStatus !== "unlocked")
    return "unknown";
  if (child.isLocked === true || child.isDisabled === true) return "blocked";
  if (
    child.reportable !== true ||
    typeof child.hash !== "string" ||
    !child.hash
  )
    return "unknown";
  const type = String(metadata.promotionType || "").toLowerCase(),
    attr = metadata.attributes || {};
  if (
    type === "search" ||
    String(attr.type || "").toLowerCase() === "search" ||
    (typeof metadata.activityProgressMax === "number" &&
      metadata.activityProgressMax > 1) ||
    (/search/i.test(child.offerId) && /(day|streak|\dx)/i.test(child.offerId))
  )
    return "deferred";
  if (
    /\/redeem\//i.test(metadata.destinationUrl || "") ||
    /(redeem|claim|(?<!url)reward)/i.test(child.offerId)
  )
    return autoClaim ? "eligible" : "manual_claim";
  return "eligible";
}
const {journal} = require("./journal.cjs");
async function execute(driver, { autoClaim = false, timezoneOffset = 0 } = {}) {
  const outcomes = [];
  const inventory = await driver.inventory();
  if (!Array.isArray(inventory) || inventory.length > 100)
    throw Error("punchcard_inventory_unavailable");
  const matches = inventory.filter(
    (p) => p?.parentPromotion?.offerId === PARENT,
  );
  if (matches.length === 0)
    return { status: "unknown", reason: "onboarding_not_observed" };
  if (matches.length !== 1) throw Error("duplicate_parent");
  const card = matches[0];
  if (card.parentPromotion.complete === true)
    return { status: "complete", reason: "parent_readback_complete" };

  if (!Array.isArray(card.childPromotions) || card.childPromotions.length > 40)
    throw Error("child_inventory_unavailable");
  const ids = new Set();
  for (const c of card.childPromotions) {
    if (!c?.offerId || ids.has(c.offerId)) throw Error("duplicate_child");
    ids.add(c.offerId);
  }
  let children = await driver.children();
  if (
    !Array.isArray(children) ||
    !children.length ||
    children.length > 40 ||
    new Set(children.map((c) => c.offerId)).size !== children.length
  )
    throw Error("child_inventory_unavailable");
  for (const child of children) {
    const state = classify(
      child,
      card.childPromotions.find((c) => c.offerId === child.offerId),
      autoClaim,
    );
    if (state !== "eligible") {
      outcomes.push(state);
      continue;
    }
    // A previous attempted write is never replayed just because current state is incomplete.
    if (driver.journal.has(child.offerId)) {
      outcomes.push("unknown");
      continue;
    }
    // Deterministic preflight failures must not create uncertain-write evidence.
    await driver.prepare?.(child, timezoneOffset);
    await driver.journal.mark(child.offerId, "attempted");
    trace.emit("journal.intent", {capability: "punchcards", offer_ref: trace.reference(child.offerId), state: "attempted"});
    try {
      await driver.submit(child, timezoneOffset);
    } catch (error) {
      trace.failure("promotion.submit", error, {capability: "punchcards", offer_ref: trace.reference(child.offerId)});
      if (error.message === "human_required") throw error;
    } // Reconcile timeout/ACK alike.
    let complete = false;
    for (let i = 0; i < 3; i++) {
      try {
        const fresh = await driver.children();
        complete =
          Array.isArray(fresh) &&
          fresh.length <= 40 &&
          fresh.filter((c) => c.offerId === child.offerId).length === 1 &&
          fresh.find((c) => c.offerId === child.offerId)?.isCompleted === true;
      } catch (error) {
        trace.failure("promotion.readback", error, {capability: "punchcards", offer_ref: trace.reference(child.offerId), attempt: i + 1});
        if (error.message === "human_required") throw error;
      }
      if (complete) break;
      if (i < 2) await driver.wait();
    }
    if (complete) await driver.journal.mark(child.offerId, "confirmed");
    trace.emit("promotion.readback", {capability: "punchcards", offer_ref: trace.reference(child.offerId), complete});
    outcomes.push(complete ? "complete" : "unknown");
  }
  const current = await driver.inventory();
  if (
    Array.isArray(current) &&
    current.filter((c) => c?.parentPromotion?.offerId === PARENT).length ===
      1 &&
    current.find((c) => c?.parentPromotion?.offerId === PARENT)?.parentPromotion
      .complete === true
  )
    return { status: "complete", reason: "parent_readback_complete" };
  return {
    status: outcomes.includes("unknown") ? "unknown" : "incomplete",
    reason: "punchcard_readback_pending",
  };
}
async function run(chromium, state, parser, options = {}, deps = common) {
  const pacing = options.pacing || interaction.create(options.interaction);
  try {
    return await deps.withBrowser(
      chromium,
      state,
      options,
      async (context, page) => {
        await page.goto(deps.EARN, {waitUntil: "domcontentloaded", timeout: 45000});
        await deps.guard(page);
        common.assertAccountAvailable(await deps.readFlyout(context), options.region);
        const overview = await deps.boundedHtml(page);
        const parents = parser.snapshotQuestList(overview);
        if (parser.snapshotPage(overview).offers.length > 0 &&
            parents.length > 0 && !parents.some(p => p.offerId === PARENT))
          return {execution: "ok", reason: "onboarding_not_assigned",
            business: {punchcards: "not_applicable"}};
        async function html() {
          await page.goto(deps.EARN + "/quest/" + PARENT, {
            waitUntil: "domcontentloaded",
            timeout: 45000,
          });
          await deps.guard(page);
          return deps.boundedHtml(page);
        }
        const initial = await html();
        const ids = await actions.discover(page, parser, initial);
        const driver = {
          journal: options.journal,
          async inventory() {
            const raw = await deps.readFlyout(context);
            common.assertAccountAvailable(raw, options.region);
            await page.goto(deps.EARN, {
              waitUntil: "domcontentloaded",
              timeout: 45000,
            });
            await deps.guard(page);
            const parents = parser.snapshotQuestList(
              await deps.boundedHtml(page),
            );
            if (!parents.some((p) => p.offerId === PARENT)) return [];
            const text = await html();
            const objects = parser.extractObjects(
              parser.concatFlightChunks(text),
              '"offerId"',
            );
            const children = parser.snapshotQuestPage(text).map((child) => {
              const rows = objects.filter((o) => o.offerId === child.offerId);
              const rawChild = rows.length === 1 ? rows[0] : {};
              return {
                offerId: child.offerId,
                complete: child.isCompleted,
                promotionType: rawChild.promotionType,
                attributes: rawChild.attributes,
                activityProgressMax: rawChild.activityProgressMax,
                destinationUrl: rawChild.destinationUrl ?? rawChild.destination,
                exclusiveLockedFeatureStatus:
                  rawChild.isLocked === false && rawChild.isDisabled === false
                    ? "unlocked"
                    : "unknown",
              };
            });
            return [
              {
                parentPromotion: parents.find((p) => p.offerId === PARENT),
                childPromotions: children,
              },
            ];
          },
          async children() {
            return parser.snapshotQuestPage(await html());
          },
          async prepare(child, offset) {
            actions.validateSubmission(
              ids.reportActivity,
              PARENT,
              child,
              offset,
            );
            await pacing.pause(page, "action");
            await deps.guard(page);
          },
          async submit(child, offset) {
            return actions.submit(
              page,
              parser,
              ids.reportActivity,
              PARENT,
              child,
              offset,
            );
          },
          wait: () => page.waitForTimeout(3000),
        };
        const out = await execute(driver, {...options,
          timezoneOffset: Number(await common.timezoneOffset(page, options.timezoneOffset))});
        return {
          execution: "ok",
          reason: out.reason,
          business: { punchcards: out.status },
        };
      },
    );
  } catch (error) {
    trace.failure("promotion.submit", error, {capability: "punchcards"});
    deps.recordObstacle(error, {
      capability: "punchcards",
      phase: "onboarding",
    });
    return {
      execution: "failed",
      reason:
        error.message === "human_required"
          ? "human_required"
          : error.details?.code || "punchcards_unconfirmed",
      business: { punchcards: "unknown" },
    };
  }
}
async function main() {
  let out;
  try {
    const dir = process.env.BENEFITS_STATE_DIR;
    const {readConfig, browserOptions} = require("./runtime_config.cjs");
    const config = readConfig(process.env.BENEFITS_STATE_DIR);
    out = await run(
      common.dependency(process.env.REWARDS_ROOT),
      common.readState(dir),
      loadParser(),
      {
        ...browserOptions(process.env.BENEFITS_STATE_DIR, config, process.env.REWARDS_PROXY),
        autoClaim: config.punchcards?.autoClaim === true,
        journal: journal(path.join(dir, "punchcard-journal.json")),
      },
    );
  } catch (error) {
    trace.failure("run", error, {capability: "punchcards"});
    out = {
      execution: "failed",
      reason: "punchcard_configuration_unavailable",
      business: { punchcards: "unknown" },
    };
  }
  publish(out.execution, out.reason, out.business);
}
if (require.main === module) main();
module.exports = { PARENT, classify, journal, execute, run };
