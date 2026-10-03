"use strict";
// Adapted protocol logic: TheNetsky/Microsoft-Rewards-Script v4.3.2, GPL-3.0-or-later.
// Full license and exact source commit are retained under vendor/rewards-parser.
const fs = require("node:fs"),
  path = require("node:path");
const common = require("./browser_common.cjs"),
  actions = require("./server_actions.cjs");
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
function journal(file) {
  let rows = {};
  if (fs.existsSync(file)) rows = common.boundedJson(file, 65536);
  if (
    !rows ||
    Array.isArray(rows) ||
    typeof rows !== "object" ||
    Object.keys(rows).length > 100 ||
    Object.values(rows).some((v) => !["attempted", "confirmed"].includes(v))
  )
    throw Error("journal_invalid");
  return {
    has: (id) => Object.hasOwn(rows, id),
    async mark(id, status) {
      if (
        !/^[A-Za-z0-9_-]{1,200}$/.test(id) ||
        (Object.keys(rows).length >= 100 && !Object.hasOwn(rows, id))
      )
        throw Error("journal_limit");
      rows[id] = status;
      const temp = file + ".tmp";
      fs.writeFileSync(temp, JSON.stringify(rows), { mode: 0o600 });
      fs.renameSync(temp, file);
    },
  };
}
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
    try {
      await driver.submit(child, timezoneOffset);
    } catch (error) {
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
        if (error.message === "human_required") throw error;
      }
      if (complete) break;
      if (i < 2) await driver.wait();
    }
    if (complete) await driver.journal.mark(child.offerId, "confirmed");
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
  try {
    return await deps.withBrowser(
      chromium,
      state,
      options,
      async (context, page) => {
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
        const out = await execute(driver, options);
        return {
          execution: "ok",
          reason: out.reason,
          business: { punchcards: out.status },
        };
      },
    );
  } catch (error) {
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
    const configFile = path.join(dir, "native-config.json");
    const config = fs.existsSync(configFile)
      ? common.boundedJson(configFile, 65536)
      : {};
    out = await run(
      common.dependency(process.env.REWARDS_ROOT),
      common.readState(dir),
      loadParser(),
      {
        proxy: process.env.REWARDS_PROXY,
        autoClaim: config.punchcards?.autoClaim === true,
        timezoneOffset: config.timezoneOffset ?? 0,
        journal: journal(path.join(dir, "punchcard-journal.json")),
      },
    );
  } catch {
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
