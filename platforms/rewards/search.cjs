"use strict";
// Independent sequential quota search; source behavior mapped in docs/REWARDS_PARITY.md.
const path = require("node:path");
const common = require("./browser_common.cjs");
const trace = require("./telemetry.cjs");
const interaction = require("./interaction.cjs");
const { publish } = require("../../common/result.cjs");
const {metric} = require("../../common/details.cjs");
function amount(value) {
  if (
    value === null ||
    value === undefined ||
    typeof value === "boolean" ||
    (typeof value === "string" && !value.trim())
  )
    return null;
  const n = Number(value);
  return Number.isFinite(n) && n >= 0 ? n : null;
}
function quota(rows) {
  if (!Array.isArray(rows) || rows.length > 32)
    return { status: "unknown", earned: null, max: null };
  if (rows.length === 0) return { status: "not_applicable", earned: 0, max: 0 };
  let earned = 0,
    max = 0;
  for (const row of rows) {
    const c = amount(row?.pointProgress),
      m = amount(row?.pointProgressMax);
    if (c === null || m === null || m <= 0)
      return { status: "unknown", earned: null, max: null };
    earned += Math.min(c, m);
    max += m;
  }
  return { status: earned >= max ? "complete" : "incomplete", earned, max };
}
const restricted = common.restricted;
function quotas(raw, device, expectedRegion = null) {
  common.assertAccountAvailable(raw, expectedRegion);
  const counters = raw.flyoutResult.userStatus.counters || {};
  if (device === "mobile")
    return {
      mobile_search: quota(counters.MobileSearch ?? counters.mobileSearch),
    };
  const pc = counters.PCSearch ?? counters.pcSearch;
  if (!Array.isArray(pc))
    return { desktop_search: quota(null), edge_search: quota(null) };
  const edge = (x) =>
    [x?.offerId, x?.name, x?.title, x?.promotionSubtype].some(
      (v) => typeof v === "string" && /(^|[_\s-])edge([_\s-]|$)/i.test(v),
    );
  return {
    desktop_search: quota(pc.filter((x) => !edge(x))),
    edge_search: quota(pc.filter(edge)),
  };
}
function normalized(value) {
  return String(value).trim().replace(/\s+/g, " ").toLowerCase();
}
function queryQueue(queries, clusters = {}, clusterSearch = false) {
  if (!Array.isArray(queries) || queries.length > 1000)
    throw Error("query_inventory_invalid");
  const seen = new Set(),
    out = [];
  for (const query of queries) {
    if (typeof query !== "string" || query.length > 300) continue;
    const rows = clusterSearch
      ? [
          query,
          ...(Array.isArray(clusters[query])
            ? clusters[query].slice(0, 8)
            : []),
        ]
      : [query];
    for (const row of rows) {
      if (typeof row !== "string" || row.length > 300) continue;
      const key = normalized(row);
      if (key && !seen.has(key)) {
        seen.add(key);
        out.push(row.trim());
      }
    }
    if (out.length >= 1000) break;
  }
  return out.slice(0, 1000);
}
function configuration(value = {}) {
  const config = {
    maxSearches: 100,
    stagnantLimit: 3,
    delayMs: 30000,
    readbackAttempts: 3,
    readbackDelayMs: 2000,
    clusterSearch: false,
    ...value,
  };
  for (const [key, min, max] of [
    ["maxSearches", 1, 100],
    ["stagnantLimit", 1, 20],
    ["delayMs", 0, 300000],
    ["readbackAttempts", 1, 10],
    ["readbackDelayMs", 0, 30000],
  ])
    if (
      !Number.isInteger(config[key]) ||
      config[key] < min ||
      config[key] > max
    )
      throw Error("invalid_search_config");
  return config;
}
function statuses(measure) {
  return Object.fromEntries(
    Object.entries(measure).map(([key, value]) => [key, value.status]),
  );
}
function total(measure) {
  return Object.values(measure).reduce((n, q) => n + q.earned, 0);
}
function terminal(measure) {
  return Object.values(measure).every((q) =>
    ["complete", "not_applicable"].includes(q.status),
  );
}
async function runSession(
  page,
  observe,
  device,
  config,
  queries,
  deps = common,
  journal,
  pacing = interaction.create(),
) {
  let measured = await observe(),
    stagnant = 0,
    performed = 0;
  trace.emit("search.readback", {device, current: total(measured), max: Object.values(measured).reduce((n,q) => n + q.max,0)});
  if (Object.values(measured).some((q) => q.status === "unknown"))
    return {
      execution: "failed",
      reason: "quota_unknown",
      business: statuses(measured),
    };
  if (terminal(measured))
    return {
      execution: "ok",
      reason: "search_already_complete",
      business: statuses(measured),
    };
  const queue = queryQueue(
    queries,
    config.clusters || {},
    config.clusterSearch,
  );
  for (const query of queue) {
    if (performed >= config.maxSearches) break;
    const queryKey = "query_" + require("node:crypto").createHash("sha256")
      .update(normalized(query)).digest("hex");
    if (journal?.has(queryKey)) { trace.emit("search.skip", {device, offer_ref: trace.reference(queryKey)}); continue; }
    await deps.guard(page);
    await pacing.rest(page, performed);
    const before = measured;
    let submitted = false;
    try {
      if (performed && performed % 10 === 0) {
        await page.goto("https://www.bing.com/", {
          waitUntil: "domcontentloaded",
          timeout: 45000,
        });
        await deps.guard(page);
      }
      const box = page.locator("#sb_form_q");
      await box.waitFor({ state: "visible", timeout: 15000 });
      await pacing.type(page, box, query);
      await deps.guard(page);
      // Persist before invocation: a timeout may have reached the server.
      // The caller binds this journal to the account, device and business day.
      if (journal) await journal.mark(queryKey, "attempted");
      trace.emit("journal.intent", {device, offer_ref: trace.reference(queryKey), state: "attempted"});
      submitted = true;
      await trace.span("search.submit", {device, count: performed + 1, offer_ref: trace.reference(queryKey)}, () => box.press("Enter"));
      performed++;
      await page
        .waitForLoadState("domcontentloaded", { timeout: 15000 })
        .catch(() => {});
      await pacing.pause(page, "settle");
      await deps.guard(page);
      await pacing.cooldown(page, config.delayMs);
    } catch (error) {
      trace.failure("search.submit", error, {device, count: performed});
      if (!submitted) throw error;
      // Preserve real authentication/challenge obstacles, even when the
      // search may already have reached Bing. A counter read cannot clear them.
      if (error.details) throw error;
      measured = await observe();
      trace.emit("search.readback", {device, reconciled: true, current: total(measured)});
      if (terminal(measured))
        return {
          execution: "ok",
          reason: "search_reconciled_after_timeout",
          business: statuses(measured),
        };
      return {
        execution: "failed",
        reason: "search_submission_uncertain",
        business: statuses(measured),
        details: {metrics: {}, items: [{id: device + "_search_submission",
          name: device + " search", status: "unknown",
          reason: error.name === "TimeoutError" ? "search_navigation_timeout"
            : "search_browser_error"}]},
      };
    }
    for (let attempt = 0; attempt < config.readbackAttempts; attempt++) {
      measured = await observe();
      trace.emit("search.readback", {device, attempt: attempt + 1, current: total(measured)});
      if (Object.values(measured).some((q) => q.status === "unknown"))
        return {
          execution: "failed",
          reason: "quota_unknown",
          business: statuses(measured),
        };
      if (total(measured) < total(before))
        return {
          execution: "failed",
          reason: "quota_regressed_reprobe_required",
          business: statuses(measured),
        };
      if (terminal(measured))
        return {
          execution: "ok",
          reason: "search_quota_confirmed",
          business: statuses(measured),
        };
      if (total(measured) > total(before)) break;
      if (attempt + 1 < config.readbackAttempts)
        await page.waitForTimeout(config.readbackDelayMs);
    }
    stagnant = total(measured) > total(before) ? 0 : stagnant + 1;
    if (stagnant >= config.stagnantLimit)
      return {
        execution: "failed",
        reason: "search_stagnant",
        business: statuses(measured),
      };
  }
  return {
    execution: "failed",
    reason:
      performed >= config.maxSearches
        ? "search_budget_exhausted"
        : "query_inventory_exhausted",
    business: statuses(measured),
  };
}
async function run(chromium, state, device, options = {}, deps = common) {
  let first, last;
  const details = () => ({metrics: Object.fromEntries(Object.entries(last || {}).map(([key,q]) =>
    [key, metric("points", q.earned, q.max, first?.[key]?.earned, q.earned,
      first?.[key]?.earned != null && q.earned != null ? q.earned - first[key].earned : null)])), items: []});
  let business =
    device === "mobile"
      ? { mobile_search: "unknown" }
      : { desktop_search: "unknown", edge_search: "unknown" };
  try {
    const config = configuration(options.search);
    if (
      device === "mobile" &&
      (!options.contextOptions?.isMobile ||
        typeof options.contextOptions?.userAgent !== "string")
    )
      return {
        execution: "failed",
        reason: "mobile_device_profile_required",
        business,
      };
    const out = await deps.withBrowser(
      chromium,
      state,
      options,
      async (context, page) => {
        await page.goto("https://www.bing.com/", {
          waitUntil: "domcontentloaded",
          timeout: 45000,
        });
        await deps.guard(page);
        const observe = async () => {
          await deps.guard(page);
          last = quotas(
            await deps.readFlyout(context, page),
            device,
            options.region,
          );
          first ||= last;
          return last;
        };
        const queries =
          config.queries ||
          require("./vendor/rewards-parser/src/functions/search-queries.json").slice(
            0,
            1000,
          );
        return runSession(page, observe, device, config, queries, deps, options.journal,
          options.pacing || interaction.create(options.interaction));
      },
    );
    return {...out, details: {...details(), items: out.details?.items || []}};
  } catch (error) {
    trace.failure("search.submit", error, {device});
    deps.recordObstacle?.(error, {
      capability: device === "mobile" ? "mobile_search" : "desktop_search",
      phase: "search",
    });
    return {
      execution: "failed",
      reason: error.details?.code || "search_unconfirmed",
      business,
      details: details(),
    };
  }
}
async function main() {
  const device = process.argv.includes("--mobile") ? "mobile" : "desktop";
  let out;
  try {
    const stateDir = process.env.BENEFITS_STATE_DIR;
    let config = {};
    try {
      config = common.boundedJson(
        path.join(stateDir, "native-config.json"),
        65536,
      );
    } catch (error) {
      if (error.code !== "ENOENT") throw error;
    }
    out = await run(
      common.dependency(process.env.REWARDS_ROOT),
      common.readState(stateDir, device),
      device,
      {
        proxy: process.env.REWARDS_PROXY,
        search: config.search,
        interaction: config.interaction,
        region: config.region,
        contextOptions: device === "mobile" ? config.mobile : config.desktop,
        journal: dailyJournal(stateDir, device, process.env.BENEFITS_BUSINESS_DATE),
      },
    );
  } catch (error) {
    trace.failure("run", error, {capability: device + "_search"});
    out = {
      execution: "failed",
      reason: "dependency_session_or_config_unavailable",
      business: { [device + "_search"]: "unknown" },
    };
  }
  publish(out.execution, out.reason, out.business, out.details);
}
if (require.main === module) main();
function dailyJournal(stateDir, device, businessDate) {
  if (!["desktop", "mobile"].includes(device) ||
      !/^\d{4}-\d{2}-\d{2}$/.test(businessDate || ""))
    throw Error("business_date_invalid");
  return require("./punchcards.cjs").journal(
    path.join(stateDir, "search-" + device + "-" + businessDate + ".json"));
}
module.exports = {
  restricted,
  amount,
  quota,
  quotas,
  queryQueue,
  configuration,
  runSession,
  run,
  dailyJournal,
};
