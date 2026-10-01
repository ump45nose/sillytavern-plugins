"use strict";
// Sequential native orchestration. Never imports the upstream autonomous Main.
const fs = require("node:fs"),
  path = require("node:path");
const common = require("./browser_common.cjs");
const { publish } = require("../../common/result.cjs");
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
async function execute(
  value,
  bindings,
  { snapshot, onProgress = async () => {} } = {},
) {
  const enabled = manifest(value),
    stages = {},
    business = {},
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
    if (!snapshot) {
      snapshots[phase] = {
        execution: "failed",
        reason: "snapshot_binding_unavailable",
        business: { snapshot: "unknown" },
      };
      return;
    }
    try {
      snapshots[phase] = validateOutput(await snapshot());
    } catch {
      snapshots[phase] = {
        execution: "failed",
        reason: "snapshot_unavailable",
        business: { snapshot: "unknown" },
      };
    }
  }
  await observe("before");
  checkStop(snapshots.before);
  for (const capability of enabled) {
    let out;
    if (stopped)
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
        out = validateOutput(await bindings[capability]());
      } catch (error) {
        out = {
          execution: "failed",
          reason: STOP.has(error.message) ? error.message : "capability_failed",
          business: { [capability]: "unknown" },
        };
      }
    stages[capability] = out;
    business[capability] = overall(out);
    failed ||= out.execution !== "ok";
    checkStop(out);
    await onProgress({
      schema_version: 1,
      enabled,
      stages,
      snapshots,
      business,
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
    report: { schema_version: 1, enabled, stages, snapshots, business },
  };
}
function createBindings({ chromium, stateDir, config = {}, proxy, host = {} }) {
  // Required account context is checked before snapshots or any APP action.
  // A failed snapshot must not accidentally turn a missing desktop state into
  // permission to execute other mutations against an unbound account.
  let desktop;
  try {
    desktop = common.readState(stateDir, "desktop");
  } catch {
    throw Error("desktop_session_unavailable");
  }
  const sessions = new Map([["desktop", desktop]]);
  const state = (device) => {
    if (!sessions.has(device))
      sessions.set(device, common.readState(stateDir, device));
    return sessions.get(device);
  };
  const preserve = (device) => (value) => sessions.set(device, value);
  const parser = require("./parser_loader.cjs").loadParser();
  const base = {
    proxy,
    contextOptions: config.desktop,
    onVerifiedState: preserve("desktop"),
  };
  const journal = require("./punchcards.cjs").journal;
  // Trusted in-process callbacks only. Never module names/grants/tokens from JSON.
  const goal = config.goal?.url
    ? {
        url: config.goal.url,
        checkpoint: host.goalCheckpoint,
        authorize: host.authorizeGoal,
        journal: journal(path.join(stateDir, "goal-journal.json")),
      }
    : undefined;
  const snapshot = () =>
    require("./snapshot.cjs").run(chromium, state("desktop"), base);
  const bindings = {
    daily: () =>
      require("./activities.cjs").run(chromium, state("desktop"), base),
    extra: () =>
      require("./extra.cjs").run(chromium, state("desktop"), parser, {
        ...base,
        goal,
      }),
    punchcards: () =>
      require("./punchcards.cjs").run(chromium, state("desktop"), parser, {
        ...base,
        autoClaim: config.punchcards?.autoClaim === true,
        timezoneOffset: config.timezoneOffset ?? 0,
        journal: journal(path.join(stateDir, "punchcard-journal.json")),
      }),
    desktop_search: () =>
      require("./search.cjs").run(chromium, state("desktop"), "desktop", {
        ...base,
        search: config.search,
        region: config.region,
      }),
    mobile_search: () =>
      require("./search.cjs").run(chromium, state("mobile"), "mobile", {
        proxy,
        search: config.search,
        region: config.region,
        contextOptions: config.mobile,
        onVerifiedState: preserve("mobile"),
      }),
  };
  if (typeof host.appClient === "function")
    for (const [capability, method] of [
      ["app_daily", "submitDaily"],
      ["app_promotions", "runPromotions"],
      ["read_to_earn", "readToEarn"],
    ])
      bindings[capability] = async () => {
        const client = await host.appClient();
        const j = journal(path.join(stateDir, "app-journal.json"));
        const app = require("./app.cjs");
        const out =
          method === "runPromotions"
            ? await app[method](client, j)
            : await app[method](client, j, host.businessDate);
        return {
          ...out,
          execution: "ok",
          reason: out.reason || "app_readback_finished",
        };
      };
  return { bindings, snapshot };
}
function writeReport(file, value) {
  const text = JSON.stringify(value);
  if (Buffer.byteLength(text) > 65536) throw Error("report_too_large");
  const temp = file + ".tmp-" + process.pid;
  fs.writeFileSync(temp, text, { mode: 0o600 });
  fs.renameSync(temp, file);
}
async function main() {
  let out;
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
    manifest(requested);
    const configPath = path.join(stateDir, "native-config.json");
    const config = fs.existsSync(configPath)
      ? common.boundedJson(configPath, 65536)
      : {};
    const native = createBindings({
      chromium: common.dependency(process.env.REWARDS_ROOT),
      stateDir,
      config,
      proxy: process.env.REWARDS_PROXY,
    });
    const reportPath = path.join(
      path.dirname(process.env.BENEFITS_RESULT_PATH),
      "rewards-report.json",
    );
    out = await execute(requested, native.bindings, {
      snapshot: native.snapshot,
      onProgress: (value) => writeReport(reportPath, value),
    });
    writeReport(reportPath, out.report);
  } catch (error) {
    out = {
      execution: "failed",
      reason: [
        "capability_manifest_required",
        "capability_manifest_invalid",
        "dependency_not_configured",
        "dependency_incompatible",
        "desktop_session_unavailable",
      ].includes(error.message)
        ? error.message
        : "full_preflight_or_reporting_failed",
      business: { full: "unknown" },
    };
  }
  publish(out.execution, out.reason, out.business);
}
if (require.main === module) main();
module.exports = {
  ORDER,
  manifest,
  validateOutput,
  overall,
  execute,
  createBindings,
  writeReport,
};
