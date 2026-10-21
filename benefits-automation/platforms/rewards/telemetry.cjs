"use strict";
// Per-run diagnostics. Only allowlisted fields reach disk; never raw exceptions.
const fs = require("node:fs"), path = require("node:path"), os = require("node:os");
const {AsyncLocalStorage} = require("node:async_hooks");
const scope = new AsyncLocalStorage();
const LIMIT = 512 * 1024;
const CAPABILITIES = new Set(("full snapshot before after daily extra punchcards desktop_search mobile_search " +
  "more_promotions claim app_daily app_promotions daily_streaks bing_streak app_streak desktop_app_weekly read_to_earn social explore goal local_smoke").split(" "));
const REASONS = new Set(("human_required captcha login_required terms_changed age_required security_prompt " +
  "account_restricted region_mismatch account_link_required app_token_missing app_token_invalid " +
  "app_token_expired_or_scope_changed app_rate_limited app_authorization_unavailable app_authorization_timeout " +
  "app_authorization_navigation_failed app_token_exchange_failed app_inventory_unavailable app_response_unavailable " +
  "app_response_too_large app_locale_invalid app_inventory_limit app_offer_invalid journal_invalid journal_limit " +
  "business_date_invalid business_date_regressed authenticated_inventory_unavailable flyout_request_failed " +
  "flyout_unavailable input_too_large session_invalid dependency_not_configured dependency_incompatible " +
  "page_too_large session_state_limit snapshot_unavailable capability_failed browser_operation_failed " +
  "search_submission_uncertain search_stagnant quota_unknown quota_regressed_reprobe_required " +
  "search_unconfirmed activation_evidence_unavailable activity_action_unavailable deployment_evidence_unavailable " +
  "action_chunks_missing action_discovery_limit ambiguous_action_id invalid_action_id counter_inventory_unavailable " +
  "inventory_unavailable offer_inventory_unavailable daily_browser_or_network_error daily_progress_unavailable " +
  "daily_journal_unavailable daily_action_unavailable daily_activity_not_credited daily_already_complete daily_complete " +
  "app_checkin_progress_unavailable previous_daily_submission_requires_reconciliation " +
  "daily_submitted_without_attributable_confirmation not_run_after_stop capability_binding_pending " +
  "full_requested_capabilities_complete full_requested_capabilities_partial full_intervention_pending " +
  "full_in_progress full_preflight_or_reporting_failed full_deadline_exceeded full_resource_busy " +
  "snapshot_binding_unavailable confirmed_before_intervention app_readback_finished " +
  "app_checkin_confirmed_by_fresh_snapshot fresh_readonly_snapshot invalid_interaction_config " +
  "invalid_interaction_random request_cancelled_during_cleanup daily_cycle_unavailable daily_cycle_changed " +
  "streak_progress_unavailable streaks_readback_finished full_task_cycle_changed platform_task_cycle " +
  "desktop_app_progress_unavailable desktop_app_weekly_changed desktop_app_weekly_unavailable " +
  "desktop_app_weekly_not_assigned desktop_app_weekly_complete desktop_app_weekly_pending desktop_app_weekly_locked " +
  "unclassified_failure").split(" "));
const NAMES = new Set(["Error", "TimeoutError", "AbortError", "TypeError", "SyntaxError",
  "RewardsObstacle", "AppAuthenticationRequired"]);
const CODES = new Set(["ECONNRESET", "ECONNREFUSED", "ETIMEDOUT", "ENOTFOUND", "EAI_AGAIN",
  "EPIPE", "ERR_NETWORK", "ERR_CERT_AUTHORITY_INVALID", "ERR_CONNECTION_RESET", "ERR_CONNECTION_CLOSED",
  "ERR_CONNECTION_REFUSED", "ERR_NAME_NOT_RESOLVED", "ERR_TIMED_OUT", "ERR_ABORTED", "ERR_BLOCKED_BY_CLIENT", "ERR_FAILED"]);
const STATES = new Set(["ok", "failed", "busy", "timeout", "complete", "unknown", "incomplete",
  "blocked", "not_applicable", "attempted", "confirmed", "http", "browser", "cached"]);
const OPERATIONS = new Set(("run stage snapshot browser.launch browser.context browser.page browser.close " +
  "browser.context_close page.goto page.waitForURL page.waitForLoadState page.request_failed " +
  "http.get http.post http.fetch server_action.request auth.http_redirect auth.browser_redirect " +
  "auth.exchange auth.cache app.request app.snapshot app.inventory app.offer app.checkin " +
  "search.submit search.readback search.skip activity.submit promotion.submit promotion.readback " +
  "interaction.pause interaction.type interaction.click interaction.review interaction.batch_break " +
  "journal.intent log.truncated log.unavailable").split(" "));
const ROUTES = new Set(["rewards_dashboard", "rewards_earn", "rewards_quest", "rewards_chunk", "bing_home",
  "bing_search", "bing_flyout", "oauth_authorize", "oauth_callback", "oauth_token", "microsoft_login",
  "app_inventory", "app_activity", "social_page", "other"]);
function route(value) {
  try {
    const u = new URL(value), h = u.hostname, p = u.pathname;
    if (u.protocol !== "https:" || u.username || u.password) return "other";
    if (h === "login.live.com") return ({"/oauth20_authorize.srf": "oauth_authorize",
      "/oauth20_desktop.srf": "oauth_callback", "/oauth20_token.srf": "oauth_token"})[p] || "microsoft_login";
    if (["account.live.com", "login.microsoftonline.com"].includes(h)) return "microsoft_login";
    if (h === "rewards.bing.com") return p === "/dashboard" ? "rewards_dashboard" :
      p === "/earn" ? "rewards_earn" : p.startsWith("/earn/quest/") ? "rewards_quest" :
      p.startsWith("/_next/") ? "rewards_chunk" : "other";
    if (["www.bing.com", "bing.com", "cn.bing.com"].includes(h)) return p === "/search" ? "bing_search" :
      p.startsWith("/rewards/panelflyout/") ? "bing_flyout" : p === "/" ? "bing_home" : "other";
    if (h === "prod.rewardsplatform.microsoft.com") return p === "/dapi/me" ? "app_inventory" :
      p === "/dapi/me/activities" ? "app_activity" : "other";
    if (["www.youtube.com", "www.tiktok.com"].includes(h)) return "social_page";
  } catch {}
  return "other";
}
function errorFields(error) {
  const message = typeof error?.message === "string" ? error.message : "";
  const netCode = message.match(/net::(ERR_[A-Z_]+)/)?.[1];
  const code = CODES.has(error?.code) ? error.code : CODES.has(error?.cause?.code) ? error.cause.code :
    CODES.has(netCode) ? netCode : undefined;
  const failure = ["TimeoutError", "AbortError"].includes(error?.name) ||
    ["ETIMEDOUT", "ERR_TIMED_OUT"].includes(code) || /timed? ?out|Timeout/i.test(message) ? "timeout" :
    ["ERR_ABORTED", "ERR_BLOCKED_BY_CLIENT"].includes(code) ? "cancelled" :
    /Execution context was destroyed|frame was detached/i.test(message) ? "navigation_context" :
    /Target closed|target page.*closed|browser.*closed/i.test(message) ? "page_closed" :
    /TLS|certificate|ERR_CERT/i.test(message) ? "tls" :
    /ECONN|ENOTFOUND|EAI_AGAIN|socket|net::/i.test(message) || code ? "network" : error?.details?.code ? "obstacle" :
    error?.name === "AppAuthenticationRequired" ? "authentication" : message === "app_rate_limited" ? "rate_limit" : "unknown";
  const result = {error_name: NAMES.has(error?.name) ? error.name : "Error", failure_class: failure,
    reason: REASONS.has(message) ? message : "unclassified_failure", ...(code ? {error_code: code} : {})};
  const frames = typeof error?.stack === "string" ? error.stack.split("\n").slice(1) : [];
  for (const frame of frames) {
    const m = frame.match(/^\s+at .*\/platforms\/rewards\/([a-z_]+\.cjs):(\d+):\d+/);
    if (m && m[1] !== "telemetry.cjs") { result.source = m[1]; result.line = Number(m[2]); break; }
  }
  return result;
}
function clean(fields) {
  const out = {};
  for (const key of ["duration_ms", "delay_ms", "timeout_ms", "status", "count", "current", "max", "attempt",
    "ttl_ms", "rss_mb", "free_memory_mb", "total_memory_mb", "swap_free_mb", "swap_total_mb", "load_1m", "characters", "line"])
    if (Number.isFinite(fields[key]) && Math.abs(fields[key]) <= 1e9) out[key] = fields[key];
  for (const key of ["refresh_required", "proxy_configured", "has_code", "state_matches", "has_error", "complete", "reconciled", "closing"])
    if (typeof fields[key] === "boolean") out[key] = fields[key];
  for (const [key, values] of [["capability", CAPABILITIES], ["phase", CAPABILITIES], ["route", ROUTES],
    ["reason", REASONS], ["state", STATES], ["execution", STATES], ["error_name", NAMES], ["error_code", CODES]])
    if (values.has(fields[key])) out[key] = fields[key];
  if (["timeout", "network", "tls", "cancelled", "navigation_context", "page_closed", "obstacle", "authentication", "rate_limit", "unknown"].includes(fields.failure_class)) out.failure_class = fields.failure_class;
  if (["document", "stylesheet", "image", "media", "font", "script", "xhr", "fetch", "other"].includes(fields.resource_type)) out.resource_type = fields.resource_type;
  if (["GET", "POST"].includes(fields.method)) out.method = fields.method;
  if (["desktop", "mobile"].includes(fields.device)) out.device = fields.device;
  if (["stage", "action", "reading", "search", "batch", "settle"].includes(fields.kind)) out.kind = fields.kind;
  if (/^[a-f0-9]{12}$/.test(fields.offer_ref || "")) out.offer_ref = fields.offer_ref;
  if (/^[a-z_]+\.cjs$/.test(fields.source || "")) out.source = fields.source;
  if (fields.business && typeof fields.business === "object") out.business = Object.fromEntries(
    Object.entries(fields.business).filter(([k,v]) => CAPABILITIES.has(k) && STATES.has(v)));
  return out;
}
function resources() {
  const result = {rss_mb: Math.round(process.memoryUsage().rss / 1048576), free_memory_mb: Math.round(os.freemem()/1048576),
    total_memory_mb: Math.round(os.totalmem()/1048576), load_1m: Math.round(os.loadavg()[0]*100)/100};
  try {
    const mem = fs.readFileSync("/proc/meminfo", "utf8");
    for (const [name, key] of [["SwapFree", "swap_free_mb"], ["SwapTotal", "swap_total_mb"]]) {
      const match = mem.match(new RegExp("^" + name + ":\\s+(\\d+) kB$", "m"));
      if (match) result[key] = Math.round(Number(match[1])/1024);
    }
  } catch {}
  return result;
}
function reference(value) { return require("node:crypto").createHash("sha256").update(String(value)).digest("hex").slice(0,12); }
function createLogger(file, context = {}, {limit = LIMIT} = {}) {
  let fd, bytes = 0, seq = 0, truncated = false, unavailable = false;
  const identity = {};
  for (const key of ["run_id", "account", "business_date"])
    if (typeof context[key] === "string" && /^[A-Za-z0-9_-]{1,64}$/.test(context[key])) identity[key] = context[key];
  function write(operation, state, fields = {}) {
    if (!OPERATIONS.has(operation) || !["start", "finish", "error", "info"].includes(state) || truncated || unavailable) return;
    try {
      fd ??= fs.openSync(file, fs.constants.O_WRONLY | fs.constants.O_APPEND | fs.constants.O_CREAT |
        fs.constants.O_EXCL | fs.constants.O_NOFOLLOW, 0o600);
      let row = JSON.stringify({schema_version: 1, timestamp: new Date().toISOString(), ...identity,
        seq: ++seq, operation, event: state, ...clean({phase: scope.getStore(), ...fields})}) + "\n";
      if (bytes + Buffer.byteLength(row) > limit - 512) {
        row = JSON.stringify({schema_version: 1, timestamp: new Date().toISOString(), ...identity,
          seq, operation: "log.truncated", event: "info"}) + "\n";
        truncated = true;
      }
      if (bytes + Buffer.byteLength(row) <= limit) { fs.writeSync(fd, row); bytes += Buffer.byteLength(row); }
    } catch {
      unavailable = true;
      // Fixed message only; a diagnostics failure must not change platform state.
      process.stderr.write("rewards_diagnostics_unavailable\n");
    }
  }
  return {write, close() { if (fd !== undefined) { fs.closeSync(fd); fd = undefined; } }};
}
let currentFile, currentLogger;
function logger() {
  const result = process.env.BENEFITS_RESULT_PATH;
  if (!result || !path.isAbsolute(result)) return null;
  const file = path.join(path.dirname(result), "rewards-events.jsonl");
  if (file !== currentFile) {
    try { currentLogger?.close(); } catch {}
    currentFile = file;
    currentLogger = createLogger(file, {run_id: process.env.BENEFITS_RUN_ID, account: process.env.BENEFITS_ACCOUNT,
      business_date: process.env.BENEFITS_BUSINESS_DATE});
  }
  return currentLogger;
}
function emit(operation, fields = {}, event = "info") { logger()?.write(operation, event, fields); }
function failure(operation, error, fields = {}) { emit(operation, {...fields, ...errorFields(error)}, "error"); }
async function span(operation, fields, work) {
  const start = performance.now(); emit(operation, fields, "start");
  try {
    const value = await work();
    let status;
    try { status = typeof value?.status === "function" ? value.status() : value?.status; } catch {}
    emit(operation, {...fields, duration_ms: Math.round(performance.now()-start), ...(Number.isFinite(status) ? {status} : {})}, "finish");
    return value;
  } catch (error) { failure(operation, error, {...fields, duration_ms: Math.round(performance.now()-start)}); throw error; }
}
const instrumented = new WeakSet();
function instrumentPage(page, lifecycle = {}) {
  if (!page || instrumented.has(page)) return page;
  instrumented.add(page);
  for (const method of ["goto", "waitForURL", "waitForLoadState"]) {
    if (typeof page[method] !== "function") continue;
    const original = page[method].bind(page);
    page[method] = (...args) => span("page." + method, {
      route: method === "goto" ? route(args[0]) : route(page.url?.()), timeout_ms: args[1]?.timeout,
    }, () => original(...args));
  }
  if (typeof page.on === "function") {
    page.on("popup", popup => instrumentPage(popup, lifecycle));
    page.on("requestfailed", request => {
      const fields = {...errorFields(Error(request.failure()?.errorText || "request_failed")),
        route: route(request.url()), resource_type: request.resourceType?.(), closing: lifecycle.closing === true};
      if (fields.closing) Object.assign(fields, {failure_class: "cancelled", reason: "request_cancelled_during_cleanup"});
      emit("page.request_failed", fields, fields.failure_class === "cancelled" ? "info" : "error");
    });
  }
  return page;
}
function instrumentRequest(request) {
  if (!request || instrumented.has(request)) return request;
  instrumented.add(request);
  for (const method of ["get", "post", "fetch"]) {
    if (typeof request[method] !== "function") continue;
    const original = request[method].bind(request);
    request[method] = (...args) => span("http." + method, {route: route(args[0]),
      method: method === "post" || args[1]?.method === "POST" ? "POST" : "GET", timeout_ms: args[1]?.timeout},
    () => original(...args));
  }
  return request;
}
function close() { try { currentLogger?.close(); } catch {} currentLogger = undefined; currentFile = undefined; }
module.exports = {emit, failure, span, route, reference, resources, errorFields, createLogger, close,
  instrumentPage, instrumentRequest, withPhase: (phase, work) => scope.run(phase, work)};
