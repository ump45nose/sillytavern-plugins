"use strict";
// Detection/state reduction only. No grant file is treated as consent and no action is executed here.
const crypto = require("node:crypto");
const OFFICIAL = new Set([
  "rewards.bing.com",
  "www.bing.com",
  "cn.bing.com",
  "bing.com",
  "login.live.com",
  "account.live.com",
  "login.microsoftonline.com",
  "www.microsoft.com",
  "account.microsoft.com",
  "privacy.microsoft.com",
]);
const APPROVAL_KINDS = {
  captcha: "captcha",
  terms_changed: "terms",
  age_required: "age_verification",
  login_required: "login",
  account_link_required: "account_link",
  security_prompt: "security_prompt",
  goal_change_required: "account_setting",
};
function cleanTarget(url) {
  const value = new URL(url);
  if (
    value.protocol !== "https:" ||
    !OFFICIAL.has(value.hostname) ||
    value.username ||
    value.password
  )
    throw Error("untrusted_target");
  return value.origin + value.pathname;
}
function evidenceFingerprint(...parts) {
  return crypto
    .createHash("sha256")
    .update(JSON.stringify(parts))
    .digest("hex");
}
function classify(observation) {
  if (!observation || typeof observation !== "object")
    throw Error("invalid_observation");
  const flags = observation.flags || {};
  let code = null;
  // Restrictions/security/consent take priority over apparently incomplete counters.
  for (const [key, value] of [
    ["accountLocked", "account_restricted"],
    ["botWarning", "account_restricted"],
    ["captcha", "captcha"],
    ["terms", "terms_changed"],
    ["age", "age_required"],
    ["permission", "security_prompt"],
    ["accountLink", "account_link_required"],
    ["login", "login_required"],
    ["networkError", "navigation_failed"],
    ["regionMismatch", "region_mismatch"],
    ["goal", "goal_change_required"],
    ["cookieBanner", "cookie_notice"],
    ["unknownLayout", "layout_changed"],
  ]) {
    if (flags[key] === true) {
      code = value;
      break;
    }
  }
  if (!code) return null;
  let target;
  try {
    target = cleanTarget(observation.url);
  } catch {
    target = "rewards_observation";
    code = "untrusted_navigation";
  }
  const kind = APPROVAL_KINDS[code] || null;
  const fingerprint = evidenceFingerprint(
    target,
    code,
    observation.safeEvidence || [],
  );
  return {
    code,
    kind,
    target,
    fingerprint,
    recovery: kind
      ? "trusted_authorization_then_reprobe"
      : ["navigation_failed", "cookie_notice"].includes(code)
        ? "bounded_safe_recovery"
        : "reprobe_before_retry",
  };
}
function resumePlan(
  checkpoint,
  observation,
  { trustedScopeResult = "approval_missing" } = {},
) {
  if (observation.completed === true)
    return { action: "reconcile", reason: "already_completed" };
  const current = classify(observation);
  if (!current)
    return { action: "reprobe_business", reason: "obstacle_no_longer_present" };
  if (!checkpoint || checkpoint.fingerprint !== current.fingerprint)
    return { action: "request_new_checkpoint", reason: "site_state_changed" };
  if (current.kind && trustedScopeResult !== null)
    return { action: "wait", reason: trustedScopeResult };
  return {
    action: current.kind ? "invoke_lazy_capability" : "bounded_safe_recovery",
    reason: current.code,
  };
}
class Obstacle extends Error {
  constructor(observation) {
    const details = classify(observation);
    super(
      details?.kind ? "human_required" : details?.code || "obstacle_unknown",
    );
    this.name = "RewardsObstacle";
    this.details = details;
  }
}
module.exports = {
  classify,
  resumePlan,
  Obstacle,
  cleanTarget,
  evidenceFingerprint,
  APPROVAL_KINDS,
};

function record(error, { capability, phase }) {
  if (!error?.details?.kind || !process.env.BENEFITS_RESULT_PATH) return false;
  const details = error.details;
  const signal = {
    schema_version: 1,
    run_id: process.env.BENEFITS_RUN_ID,
    platform: process.env.BENEFITS_PLATFORM,
    account: process.env.BENEFITS_ACCOUNT,
    capability,
    phase,
    kind: details.kind,
    target: cleanTarget(details.target),
    fingerprint: details.fingerprint,
    ttl_seconds: 300,
  };
  const data = JSON.stringify(signal);
  if (Buffer.byteLength(data) > 8192) throw Error("signal_too_large");
  const fs = require("node:fs"),
    path = require("node:path");
  const destination = path.join(
      path.dirname(process.env.BENEFITS_RESULT_PATH),
      "obstacle-signal.json",
    ),
    temporary = destination + ".tmp-" + process.pid;
  fs.writeFileSync(temporary, data, { mode: 0o600, flag: "wx" });
  fs.renameSync(temporary, destination);
  return true;
}
module.exports.record = record;
