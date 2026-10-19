"use strict";
const test = require("node:test"), assert = require("node:assert/strict");
const fs = require("node:fs"), os = require("node:os"), path = require("node:path");
const trace = require("../platforms/rewards/telemetry.cjs");
function fixture(t) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "rewards-events-"));
  const original = process.env.BENEFITS_RESULT_PATH;
  trace.close();
  process.env.BENEFITS_RESULT_PATH = path.join(dir, "result.json");
  t.after(() => {
    trace.close();
    if (original === undefined) delete process.env.BENEFITS_RESULT_PATH;
    else process.env.BENEFITS_RESULT_PATH = original;
    fs.rmSync(dir, {recursive: true, force: true});
  });
  const file = path.join(dir, "rewards-events.jsonl");
  return {dir, file, rows: () => fs.readFileSync(file, "utf8").trim().split("\n").map(JSON.parse)};
}
test("phase start reaches disk while a browser operation is still pending", async t => {
  const f = fixture(t);
  let finish;
  const value = trace.withPhase("app_promotions", () => trace.span("browser.launch", {timeout_ms: 60000},
    () => new Promise(resolve => {finish = resolve;})));
  const [start] = f.rows();
  assert.equal(start.event, "start");
  assert.equal(start.phase, "app_promotions");
  assert.equal(start.timeout_ms, 60000);
  finish("browser");
  assert.equal(await value, "browser");
  assert.equal(f.rows()[1].event, "finish");
  assert.ok(f.rows()[1].duration_ms >= 0);
  assert.equal(fs.statSync(f.file).mode & 0o777, 0o600);
});
test("raw errors, cookies, authorization URLs, tokens, query and body never reach the log", t => {
  const f = fixture(t), secret = "PRIVATE_SENTINEL_54321";
  const e = new Error("page.goto: Timeout " + secret + " Cookie: " + secret);
  e.name = "TimeoutError";
  e.stack = `${e.name}: ${e.message}\n    at authorizationCode (/repo/platforms/rewards/app_auth.cjs:27:9)`;
  trace.failure("auth.browser_redirect", e, {url: "https://login.live.com/?code=" + secret,
    headers: {Cookie: secret}, token: secret, message: secret, body: secret, query: secret,
    source: secret, reason: secret, route: trace.route("https://login.live.com/oauth20_desktop.srf?code=" + secret)});
  const [row] = f.rows();
  assert.equal(row.failure_class, "timeout");
  assert.equal(row.reason, "unclassified_failure");
  assert.equal(row.source, "app_auth.cjs");
  assert.equal(row.line, 27);
  assert.equal(row.route, "oauth_callback");
  assert.equal(fs.readFileSync(f.file, "utf8").includes(secret), false);
  assert.equal(trace.route("https://www.bing.com/search?q=" + secret), "bing_search");
});
test("bounded log keeps complete JSON rows and records truncation once", t => {
  const f = fixture(t), log = trace.createLogger(f.file, {run_id: "fixture-run"}, {limit: 2048});
  for (let i = 0; i < 40; i++) log.write("search.readback", "info", {current: i, max: 100});
  log.close();
  assert.ok(fs.statSync(f.file).size <= 2048);
  const rows = f.rows();
  assert.equal(rows.filter(r => r.operation === "log.truncated").length, 1);
  assert.equal(rows.at(-1).operation, "log.truncated");
  assert.ok(rows.length < 40);
});
test("diagnostic I/O failure and response status getter cannot fail a business operation", async t => {
  const f = fixture(t);
  fs.writeFileSync(f.file, "existing-private-data");
  const messages = [], write = process.stderr.write;
  process.stderr.write = value => {messages.push(value); return true;};
  try {
    const result = {status() {throw Error("private-response");}};
    assert.equal(await trace.span("http.get", {}, async () => result), result);
    trace.emit("run");
  } finally {process.stderr.write = write;}
  assert.deepEqual(messages, ["rewards_diagnostics_unavailable\n"]);
  assert.equal(fs.readFileSync(f.file, "utf8"), "existing-private-data");
});
test("instrumented navigation preserves arguments, return and original exception exactly once", async t => {
  const f = fixture(t), options = {timeout: 45000, waitUntil: "commit"}, error = new Error("net::ERR_CONNECTION_RESET PRIVATE");
  let calls = 0;
  const page = {url: () => "https://www.bing.com/", goto: async (...args) => {
    calls++; assert.equal(args[1], options); if (calls > 1) throw error; return "response";
  }};
  trace.instrumentPage(page); trace.instrumentPage(page);
  assert.equal(await page.goto("https://www.bing.com/search?q=PRIVATE", options), "response");
  await assert.rejects(page.goto("https://www.bing.com/search?q=PRIVATE", options), e => e === error);
  assert.equal(calls, 2);
  assert.deepEqual(f.rows().map(r => r.event), ["start", "finish", "start", "error"]);
  assert.equal(f.rows().at(-1).failure_class, "network");
});
test("HTTP status and fixed error classes survive without private response data", async t => {
  const f = fixture(t), error = Object.assign(new Error("private endpoint"), {code: "ETIMEDOUT"});
  const request = {get: async () => ({status: () => 200}), post: async () => {throw error;}};
  trace.instrumentRequest(request);
  await request.get("https://login.live.com/oauth20_authorize.srf?state=PRIVATE");
  await assert.rejects(request.post("https://login.live.com/oauth20_token.srf", {form: {code: "PRIVATE"}}), e => e === error);
  assert.equal(f.rows()[1].status, 200);
  assert.equal(f.rows().at(-1).error_code, "ETIMEDOUT");
  assert.equal(trace.errorFields(new Error("net::ERR_CERT_AUTHORITY_INVALID PRIVATE")).failure_class, "tls");
  assert.equal(trace.errorFields(Object.assign(new Error("aborted"), {name: "AbortError"})).failure_class, "timeout");
  assert.equal(fs.readFileSync(f.file, "utf8").includes("PRIVATE"), false);
});
test("full report preserves confirmed tasks and app failure while telemetry retains the failing stage", async t => {
  const f = fixture(t), {execute} = require("../platforms/rewards/full.cjs");
  const out = await execute({schema_version: 1, enabled: ["daily", "app_promotions"]}, {
    daily: async () => ({execution: "ok", reason: "fixture", business: {daily: "complete"}}),
    app_promotions: async () => {throw Error("app_authorization_timeout");},
  }, {snapshot: async () => ({execution: "ok", reason: "fixture", business: {daily: "complete", app_promotions: "unknown"}})});
  assert.equal(out.business.daily, "complete");
  assert.equal(out.business.app_promotions, "unknown");
  assert.ok(out.details.items.some(r => r.reason === "app_authorization_timeout"));
  assert.ok(f.rows().some(r => r.operation === "stage" && r.event === "error" &&
    r.capability === "app_promotions" && r.reason === "app_authorization_timeout"));
});
test("full report retains a private-safe stage failure after the event log fills", async t => {
  const f = fixture(t), {execute} = require("../platforms/rewards/full.cjs");
  for (let i = 0; i < 6000; i++) trace.emit("page.request_failed", {route: "other"});
  assert.equal(f.rows().at(-1).operation, "log.truncated");
  const secret = "PRIVATE_FAILURE_SENTINEL";
  const error = Object.assign(new Error("socket failure " + secret), {code: "ECONNRESET"});
  error.stack = `Error: ${secret}\n    at send (/repo/platforms/rewards/app.cjs:133:30)`;
  const out = await execute({schema_version: 1, enabled: ["app_daily"]}, {
    app_daily: async () => {throw error;},
  }, {snapshot: async () => ({execution: "ok", reason: "fresh_readonly_snapshot", business: {app_daily: "incomplete"}})});
  const diagnostic = out.report.stages.app_daily.diagnostic;
  assert.equal(out.execution, "failed");
  assert.equal(out.business.app_daily, "unknown");
  assert.equal(diagnostic.failure_class, "network");
  assert.equal(diagnostic.error_code, "ECONNRESET");
  assert.equal(diagnostic.source, "app.cjs");
  assert.equal(diagnostic.line, 133);
  assert.equal(JSON.stringify(out.report).includes(secret), false);
});
test("page cleanup cancellations remain informational while transport failures keep fixed codes", t => {
  const f = fixture(t), handlers = {}, lifecycle = {closing: false};
  trace.instrumentPage({on: (name, handler) => {handlers[name] = handler;}}, lifecycle);
  const request = code => ({failure: () => ({errorText: "net::" + code + " PRIVATE"}),
    url: () => "https://www.bing.com/search?q=PRIVATE", resourceType: () => "document"});
  handlers.requestfailed(request("ERR_CONNECTION_RESET"));
  handlers.requestfailed(request("ERR_ABORTED"));
  lifecycle.closing = true;
  handlers.requestfailed(request("ERR_FAILED"));
  const rows = f.rows();
  assert.equal(rows[0].event, "error"); assert.equal(rows[0].error_code, "ERR_CONNECTION_RESET");
  assert.equal(rows[1].event, "info"); assert.equal(rows[1].failure_class, "cancelled");
  assert.equal(rows[2].reason, "request_cancelled_during_cleanup");
  assert.equal(rows[2].closing, true); assert.equal(rows[2].resource_type, "document");
  assert.equal(fs.readFileSync(f.file, "utf8").includes("PRIVATE"), false);
});
