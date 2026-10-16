"use strict";
// Sequential native orchestration. Never imports the upstream autonomous Main.
const fs = require("node:fs"),
  path = require("node:path");
const common = require("./browser_common.cjs");
const trace = require("./telemetry.cjs");
const interaction = require("./interaction.cjs");
const { publish } = require("../../common/result.cjs");
const {metric, validateDetails} = require("../../common/details.cjs");
const ORDER = Object.freeze([
  "daily",
  "extra",
  "punchcards",
  "desktop_search",
  "mobile_search",
  "bonus_search",
  "more_promotions",
  "claim",
  "search_perk",
  "streak_protection",
  "app_daily",
  "app_promotions",
  "read_to_earn",
  "visual_search",
  "experimental_api_search",
  "experimental_api_search_on_bing",
  "experimental_edge_browsing",
]);
const STATES = new Set([
  "complete",
  "incomplete",
  "unknown",
  "not_applicable",
  "blocked",
]);
const STOP = new Set([
  "human_required",
  "captcha",
  "terms_changed",
  "age_required",
  "login_required",
  "account_link_required",
  "security_prompt",
  "account_restricted",
  "region_mismatch",
  "app_token_missing",
  "app_token_expired_or_scope_changed",
  "app_rate_limited",
  "app_authorization_unavailable",
  "app_authorization_timeout",
  "app_authorization_navigation_failed",
]);
const PUBLIC_FAILURES = new Set([
  ...STOP, "app_token_invalid", "app_token_exchange_failed",
  "app_inventory_unavailable", "app_response_unavailable",
  "app_response_too_large", "app_locale_invalid", "journal_invalid",
  "journal_limit", "business_date_invalid",
]);
function manifest(value) {
  if (
    !value ||
    Array.isArray(value) ||
    typeof value !== "object" ||
    Object.keys(value).some(
      (k) => !["schema_version", "enabled"].includes(k),
    ) ||
    value.schema_version !== 1 ||
    !Array.isArray(value.enabled) ||
    !value.enabled.length ||
    value.enabled.length > ORDER.length
  )
    throw Error("capability_manifest_invalid");
  if (
    value.enabled.some((k) => typeof k !== "string" || !ORDER.includes(k)) ||
    new Set(value.enabled).size !== value.enabled.length
  )
    throw Error("capability_manifest_invalid");
  return ORDER.filter((k) => value.enabled.includes(k));
}
function validateOutput(out) {
  if (
    !out ||
    !["ok", "failed", "timeout", "busy"].includes(out.execution) ||
    !out.business ||
    Array.isArray(out.business) ||
    typeof out.business !== "object"
  )
    throw Error("capability_result_invalid");
  const entries = Object.entries(out.business);
  if (
    !entries.length ||
    entries.length > 16 ||
    entries.some(
      ([key, v]) => !/^[a-z][a-z0-9_]{0,47}$/.test(key) || !STATES.has(v),
    )
  )
    throw Error("capability_result_invalid");
  return {
    execution: out.execution,
    reason:
      typeof out.reason === "string" && /^[a-z0-9_]{1,100}$/.test(out.reason)
        ? out.reason
        : "capability_finished",
    business: Object.fromEntries(entries),
    ...(out.details ? {details: validateDetails(out.details)} : {}),
  };
}
function overall(out) {
  const states = Object.values(out.business);
  if (states.every((v) => v === "not_applicable")) return "not_applicable";
  if (states.every((v) => ["complete", "not_applicable"].includes(v)))
    return "complete";
  if (states.includes("unknown")) return "unknown";
  if (states.includes("blocked")) return "blocked";
  return "incomplete";
}
function stopReason(out) {
  if (out.execution === "timeout") return "full_deadline_exceeded";
  if (out.execution === "busy") return "full_resource_busy";
  return STOP.has(out.reason) ? "full_intervention_pending" : null;
}
function deliveryDetails(snapshots, stages) {
  const before = snapshots.before?.details?.metrics || {},
    after = {...Object.assign({}, ...Object.values(stages).map(s => s.details?.metrics || {})),
      ...snapshots.after?.details?.metrics}, metrics = {};
  for (const key of new Set([...Object.keys(before), ...Object.keys(after)])) {
    const b = before[key], a = after[key], unit = (a || b).unit;
    // current is the latest confirmed same-run observation. after remains null
    // when no post-operation readback was possible; preserve the earlier facts.
    metrics[key] = metric(unit, a?.current ?? b?.current, a?.max ?? b?.max, b?.current, a?.current,
      b?.current != null && a?.current != null ? a.current - b.current : null);
  }
  const rows = snapshots.after?.details?.items || snapshots.before?.details?.items || [];
  const items = new Map(rows.map(row => [row.id, row]));
  for (const stage of Object.values(stages))
    for (const row of stage.details?.items || []) items.set(row.id, {...row,
      name: row.name === row.id && items.has(row.id) ? items.get(row.id).name : row.name});
  return {metrics, items: [...items.values()].slice(0,100)};
}
async function execute(
  value,
  bindings,
  { snapshot, onProgress = async () => {}, betweenStages = async () => {} } = {},
) {
  const enabled = manifest(value),
    stages = {},
    business = Object.fromEntries(enabled.map((key) => [key, "unknown"])),
    snapshots = {};
  let stopped = null,
    terminal = null,
    failed = false;
  function checkStop(out) {
    const reason = stopReason(out);
    if (reason) {
      stopped = reason;
      terminal = ["timeout", "busy"].includes(out.execution)
        ? out.execution
        : "failed";
      failed = true;
    }
  }
  async function observe(phase) {
    trace.emit("snapshot", {phase, ...trace.resources()}, "start");
    if (!snapshot) {
      snapshots[phase] = {
        execution: "failed",
        reason: "snapshot_binding_unavailable",
        business: { snapshot: "unknown" },
      };
      return;
    }
    try {
      snapshots[phase] = validateOutput(await trace.withPhase(phase, snapshot));
    } catch (error) {
      trace.failure("snapshot", error, {phase});
      snapshots[phase] = {
        execution: "failed",
        reason: "snapshot_unavailable",
        business: { snapshot: "unknown" },
      };
    }
    trace.emit("snapshot", {phase, execution: snapshots[phase].execution,
      reason: snapshots[phase].reason, business: snapshots[phase].business}, "finish");
  }
  await observe("before");
  checkStop(snapshots.before);
  for (const capability of enabled) {
    if (!stopped && Object.keys(stages).length) await trace.withPhase(capability, betweenStages);
    const stageStart = performance.now();
    trace.emit("stage", {capability, ...trace.resources()}, "start");
    let out;
    if (stopped && ["complete", "not_applicable"].includes(
      snapshots.before.business[capability]))
      out = {execution: "ok", reason: "confirmed_before_intervention",
        business: {[capability]: snapshots.before.business[capability]}};
    else if (stopped)
      out = {
        execution: "failed",
        reason: "not_run_after_stop",
        business: { [capability]: "blocked" },
      };
    else if (typeof bindings[capability] !== "function")
      out = {
        execution: "failed",
        reason: "capability_binding_pending",
        business: { [capability]: "unknown" },
      };
    else
      try {
        out = validateOutput(await trace.withPhase(capability, bindings[capability]));
      } catch (error) {
        trace.failure("stage", error, {capability});
        out = {
          execution: "failed",
          reason: PUBLIC_FAILURES.has(error.message) ? error.message : "capability_failed",
          business: { [capability]: "unknown" },
          details: {metrics: {}, items: [{id: capability + "_diagnostic", name: capability,
            status: "unknown", reason: PUBLIC_FAILURES.has(error.message) ? error.message : "capability_failed"}]},
        };
      }
    stages[capability] = out;
    trace.emit("stage", {capability, execution: out.execution, reason: out.reason,
      business: out.business, duration_ms: Math.round(performance.now()-stageStart), ...trace.resources()}, "finish");
    business[capability] = overall(out);
    failed ||= out.execution !== "ok";
    checkStop(out);
    await onProgress({
      schema_version: 1,
      enabled,
      stages,
      snapshots,
      business,
      details: deliveryDetails(snapshots, stages),
    });
  }
  if (!stopped) {
    await observe("after");
    checkStop(snapshots.after);
  } else
    snapshots.after = {
      execution: "failed",
      reason: "not_run_after_stop",
      business: { snapshot: "unknown" },
    };
  const weeklyQuest = out => out?.details?.items?.find(row => row.id === "desktop_app_weekly_quest")?.url;
  const weeklyBefore = weeklyQuest(snapshots.before), weeklyAfter = weeklyQuest(snapshots.after);
  const weeklyChanged = enabled.includes("desktop_app_weekly") &&
    weeklyBefore && weeklyAfter && weeklyBefore !== weeklyAfter;
  if (!stopped && enabled.includes("desktop_app_weekly") &&
      snapshots.after.execution === "ok" && weeklyBefore && weeklyBefore === weeklyAfter &&
      (!weeklyQuest(stages.desktop_app_weekly) || weeklyQuest(stages.desktop_app_weekly) === weeklyAfter) &&
      snapshots.after.business.desktop_app_weekly === "complete") {
    // The final weekly read verifies every opened child and its credited points.
    // Replace stale stage rows as well as the aggregate; never replay the POST.
    business.desktop_app_weekly = "complete";
    const week = weeklyAfter.split("/quest/")[1].replace("WW_pcparent_", "");
    stages.desktop_app_weekly = {execution: "ok", reason: "desktop_app_confirmed_by_fresh_snapshot",
      business: {desktop_app_weekly: "complete"}, details: {
        metrics: Object.fromEntries(Object.entries(snapshots.after.details.metrics)
          .filter(([key]) => key.startsWith("desktop_app_"))),
        items: snapshots.after.details.items.filter(row => row.id === "desktop_app_weekly_quest" ||
          /^WW_pcchild[2-8]_urlreward_/.test(row.id) && row.id.endsWith("_" + week)),
      }};
    failed = Object.values(stages).some(out => out.execution !== "ok");
  }
  if (weeklyChanged) {
    failed = true;
    stopped = "full_task_cycle_changed";
    business.desktop_app_weekly = "unknown";
  }
  // Only a fresh, attributable page counter confirms APP check-in. A POST ACK
  // or a balance increase cannot establish which task credited those points.
  if (!stopped && enabled.includes("app_daily") &&
      snapshots.after.execution === "ok" &&
      snapshots.after.business.app_daily === "complete") {
    business.app_daily = "complete";
    stages.app_daily = {...stages.app_daily, execution: "ok",
      reason: "app_checkin_confirmed_by_fresh_snapshot",
      business: {app_daily: "complete"}};
    failed = Object.values(stages).some(out => out.execution !== "ok");
  }
  const complete = Object.values(business).every((v) =>
    ["complete", "not_applicable"].includes(v),
  );
  return {
    execution: terminal || (failed ? "failed" : "ok"),
    reason:
      stopped ||
      (complete && !failed
        ? "full_requested_capabilities_complete"
        : "full_requested_capabilities_partial"),
    business,
    details: deliveryDetails(snapshots, stages),
    report: { schema_version: 1, enabled, stages, snapshots, business,
      details: deliveryDetails(snapshots, stages) },
  };
}
function createBindings({
  chromium,
  stateDir,
  config = {},
  proxy,
  host = {},
  enabled,
}) {
  const requested = new Set(manifest({ schema_version: 1, enabled }));
  const pacing = interaction.create(config.interaction);
  const desktopRequired = [
    "daily",
    "extra",
    "punchcards",
    "desktop_search",
    "more_promotions",
    "claim",
  ].some((capability) => requested.has(capability));
  const mobileRequired = requested.has("mobile_search");
  // Check every required browser account before snapshots or any mutation.
  // APP-only hosts establish their account through the trusted APP client.
  const sessions = new Map();
  for (const device of [
    ...(desktopRequired ? ["desktop"] : []),
    ...(mobileRequired ? ["mobile"] : []),
  ]) {
    try {
      sessions.set(device, common.readState(stateDir, device));
    } catch {
      throw Error(device + "_session_unavailable");
    }
  }
  const state = (device) => sessions.get(device);
  const preserve = (device) => (value) => {
    writeReport(path.join(stateDir, device === "mobile" ?
      "storage-state.mobile.json" : "storage-state.json"), value, 1024 * 1024);
    sessions.set(device, value);
  };
  // Only enabled browser capabilities need Chromium. Parser-only dependencies
  // remain lazy, so a daily/search or APP request cannot fail loading a parser.
  if ((desktopRequired || mobileRequired) && !chromium)
    chromium = common.dependency(process.env.REWARDS_ROOT);
  let loadedParser;
  const parser = () =>
    (loadedParser ??= require("./parser_loader.cjs").loadParser());
  const base = {
    proxy,
    region: config.region,
    contextOptions: config.desktop,
    onVerifiedState: preserve("desktop"),
    pacing,
  };
  const mobile = {
    proxy,
    region: config.region,
    contextOptions: config.mobile,
    onVerifiedState: preserve("mobile"),
    pacing,
  };
  const journal = (name) =>
    require("./punchcards.cjs").journal(path.join(stateDir, name));
  // Trusted in-process callbacks only. Never module names/grants/tokens from JSON.
  const goal = () =>
    config.goal?.url
      ? {
          url: config.goal.url,
          checkpoint: host.goalCheckpoint,
          authorize: host.authorizeGoal,
          journal: journal("goal-journal.json"),
        }
      : undefined;
  const browserSnapshot = host.browserSnapshot || (
    desktopRequired || mobileRequired
      ? () =>
          require("./snapshot.cjs").run(
            chromium,
            state(desktopRequired ? "desktop" : "mobile"),
            desktopRequired ? base : mobile,
          )
      : async () => ({
          execution: "ok",
          reason: "browser_snapshot_not_required",
          business: { snapshot: "not_applicable" },
        }));
  const bindings = {
    more_promotions: () => require("./promotions.cjs").run(
      chromium, state("desktop"), parser(), {...base,
        journal: journal("promotions-" + (host.businessDate || process.env.BENEFITS_BUSINESS_DATE) + ".json"),
        businessDate: process.env.BENEFITS_BUSINESS_DATE,
        timezoneOffset: config.timezoneOffset}, "more_promotions"),
    claim: () => require("./promotions.cjs").run(
      chromium, state("desktop"), parser(), {...base,
        journal: journal("claim-journal.json"),
        businessDate: process.env.BENEFITS_BUSINESS_DATE}, "claim"),
    daily: () =>
      require("./activities.cjs").run(chromium, state("desktop"), base),
    extra: () =>
      require("./extra.cjs").run(chromium, state("desktop"), parser(), {
        ...base,
        goal: goal(),
        journal: journal("explore-" + process.env.BENEFITS_BUSINESS_DATE + ".json"),
        timezoneOffset: config.timezoneOffset,
      }),
    punchcards: () =>
      require("./punchcards.cjs").run(chromium, state("desktop"), parser(), {
        ...base,
        autoClaim: config.punchcards?.autoClaim === true,
        timezoneOffset: config.timezoneOffset,
        journal: journal("punchcard-journal.json"),
      }),
    desktop_search: () =>
      require("./search.cjs").run(chromium, state("desktop"), "desktop", {
        ...base,
        search: config.search,
        journal: require("./search.cjs").dailyJournal(stateDir, "desktop",
          host.businessDate || process.env.BENEFITS_BUSINESS_DATE),
      }),
    mobile_search: () =>
      require("./search.cjs").run(chromium, state("mobile"), "mobile", {
        ...mobile,
        search: config.search,
        journal: require("./search.cjs").dailyJournal(stateDir, "mobile",
          host.businessDate || process.env.BENEFITS_BUSINESS_DATE),
      }),
  };
  let appSession, appSessionPromise;
  const appClient = host.appClient || (async () => {
    // Share even a rejected authorization attempt within this invocation. A
    // snapshot failure must not launch the same OAuth flow again at each stage.
    appSession = await (appSessionPromise ||= require("./app_auth.cjs").create({
      stateDir, proxy, state: state("desktop"), chromium, config,
      onVerifiedState: preserve("desktop"),
    }));
    return appSession.client;
  });
  const snapshot = async () => {
    const out = await browserSnapshot();
    if (requested.has("app_daily") && require("./app_checkin.cjs").counter(out) === 1)
      require("./app.cjs").checkinJournal(stateDir,
        host.businessDate || process.env.BENEFITS_BUSINESS_DATE).confirm();
    if (out.execution === "ok" && requested.has("app_promotions")) {
      try {
        const rows = require("./app.cjs").promotions(await (await appClient()).read());
        out.business.app_promotions = rows.length === 0 ? "not_applicable" :
          rows.every(row => row.complete === true) ? "complete" : "unknown";
        out.details ||= {metrics: {}, items: []};
        out.details.metrics.app_promotions = metric("count",
          rows.filter(row => row.complete === true).length, rows.length);
      } catch (error) {
        trace.failure("app.snapshot", error);
        out.business.app_promotions = "unknown";
      }
    }
    return out;
  };
  if (["app_daily", "app_promotions", "read_to_earn"].some(key => requested.has(key)))
    for (const [capability, method] of [
      ["app_daily", "submitDaily"],
      ["app_promotions", "runPromotions"],
      ["read_to_earn", "readToEarn"],
    ])
      bindings[capability] = async () => {
        // Recheck APP progress at its stage, even when the initial snapshot was
        // complete. A long full run may cross a platform reset. Authenticate
        // only when that fresh observation actually permits a submission.
        const client = method === "submitDaily" ? appClient : await appClient();
        const app = require("./app.cjs");
        const out =
          method === "runPromotions"
            ? await app[method](client, journal("app-journal.json"), {beforeSubmit: () => pacing.pause(null, "action")})
            : await app[method](
                client,
                (method === "submitDaily" ? app.checkinJournal : app.dailyJournal)(stateDir,
                  host.businessDate || process.env.BENEFITS_BUSINESS_DATE),
                host.businessDate || process.env.BENEFITS_BUSINESS_DATE,
                method === "submitDaily" ? {observeDaily: browserSnapshot,
                  beforeSubmit: () => pacing.pause(null, "action")} : {
                    beforeSubmit: () => pacing.pause(null, "action"),
                    wait: () => pacing.pause(null, "reading", 30000)},
              );
        return {
          ...out,
          execution: out.execution || "ok",
          reason: out.reason || "app_readback_finished",
        };
      };
  return {
    bindings: Object.fromEntries(
      Object.entries(bindings).filter(([key]) => requested.has(key)),
    ),
    snapshot,
    betweenStages: () => pacing.pause(null, "stage"),
    close: async () => { if (appSession) await appSession.close(); },
  };
}
function writeReport(file, value, max = 65536) {
  const text = JSON.stringify(value);
  if (Buffer.byteLength(text) > max) throw Error("report_too_large");
  const temp = file + ".tmp-" + process.pid;
  fs.writeFileSync(temp, text, { mode: 0o600 });
  fs.renameSync(temp, file);
}
async function main() {
  let out, confirmedBusiness, confirmedDetails;
  const start = performance.now();
  trace.emit("run", {...trace.resources()}, "start");
  try {
    const stateDir = process.env.BENEFITS_STATE_DIR;
    let requested;
    try {
      requested = common.boundedJson(
        path.join(stateDir, "capabilities.json"),
        16384,
      );
    } catch (error) {
      throw Error(
        error.code === "ENOENT"
          ? "capability_manifest_required"
          : "capability_manifest_invalid",
      );
    }
    const enabled = manifest(requested);
    confirmedBusiness = Object.fromEntries(
      enabled.map((capability) => [capability, "unknown"]),
    );
    const configPath = path.join(stateDir, "native-config.json");
    const config = fs.existsSync(configPath)
      ? common.boundedJson(configPath, 65536)
      : {};
    const native = createBindings({
      stateDir,
      config,
      enabled,
      proxy: process.env.REWARDS_PROXY,
    });
    const reportPath = path.join(
      path.dirname(process.env.BENEFITS_RESULT_PATH),
      "rewards-report.json",
    );
    try { out = await execute(requested, native.bindings, {
      snapshot: native.snapshot,
      betweenStages: native.betweenStages,
      onProgress: (value) => {
        // Publish the existing protocol first: the runner can recover confirmed
        // same-run business even if a later stage or report write never returns.
        confirmedBusiness = { ...value.business };
        confirmedDetails = value.details;
        publish("failed", "full_in_progress", confirmedBusiness, confirmedDetails);
        writeReport(reportPath, value);
      },
    }); } finally { await native.close(); }
    writeReport(reportPath, out.report);
  } catch (error) {
    trace.failure("run", error);
    out = {
      execution: "failed",
      reason: [
        "capability_manifest_required",
        "capability_manifest_invalid",
        "dependency_not_configured",
        "dependency_incompatible",
        "desktop_session_unavailable",
        "mobile_session_unavailable",
      ].includes(error.message)
        ? error.message
        : "full_preflight_or_reporting_failed",
      business: out?.business || confirmedBusiness || { full: "unknown" },
      details: out?.details || confirmedDetails,
    };
  }
  publish(out.execution, out.reason, out.business, out.details);
  trace.emit("run", {execution: out.execution, reason: out.reason, business: out.business,
    duration_ms: Math.round(performance.now()-start), ...trace.resources()}, "finish");
  trace.close();
}
if (require.main === module) main();
module.exports = {
  ORDER,
  manifest,
  validateOutput,
  overall,
  execute,
  deliveryDetails,
  createBindings,
  writeReport,
  main,
};
