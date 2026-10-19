"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const {APP_ID, KDT_ID, MerchantError, sessionValue, configValue, transport, run} =
  require("../platforms/yingshijufeng/adapter.cjs");
const {store, binding, readPrivate, writePrivate} = require("../platforms/yingshijufeng/state.cjs");
const {validateDetails} = require("../common/details.cjs");

const config = configValue({wechat: {url: "http://127.0.0.1:8000", token: "private-test-key", account: "account1"}});
const session = {accessToken: "test-token", sessionId: "test-session", kdtId: KDT_ID, cookie: "session=test"};
const DAY = "2026-10-19";

function fixture(t, {cached = true, pending = false, complete = false} = {}) {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "benefits-yingshijufeng-"));
  t.after(() => fs.rmSync(directory, {recursive: true, force: true}));
  const owner = binding("main", config.wechat);
  const state = store(directory, owner, DAY);
  if (cached) state.saveSession({...session});
  if (pending || complete) state.setAction("6287727", complete ? "complete" : "pending");
  let codes = 0;
  const calls = [];
  const defaults = {
    points: () => ({current_points: calls.filter(row => row.kind === "points").length === 1 ? 100 : 105}),
    page: () => ({checkinId: 6287727, showPage: false, isShow: false}),
    login: () => ({...session, accessToken: "new-token"}),
    checkin: () => ({list: [], desc: "签到成功"}),
  };
  return {state, directory, owner, calls, codes: () => codes,
    async execute(overrides = {}, extra = {}) {
      const handlers = {...defaults, ...overrides};
      return run({config, state, async request(kind, current, data) {
        calls.push({kind, session: current ? {...current} : null, data});
        return handlers[kind](current, data);
      }, async getCode(wechat, appid) {
        assert.equal(wechat, config.wechat);
        assert.equal(appid, APP_ID);
        codes++;
        return "one-use-code";
      }, ...extra});
    }};
}

test("cached session signs once, preserves a receipt, and reads the balance delta", async t => {
  const f = fixture(t);
  const snapshots = [];
  const out = await f.execute({}, {snapshot: value => snapshots.push(value)});
  assert.equal(out.execution, "ok");
  assert.deepEqual(out.business, {checkin: "complete", points: "complete"});
  assert.equal(out.details.metrics.balance.delta, 5);
  validateDetails(out.details);
  assert.equal(f.codes(), 0);
  assert.deepEqual(f.calls.map(x => x.kind), ["points", "page", "checkin", "page", "points"]);
  assert.equal(f.state.action().status, "complete");
  assert.equal(snapshots[0].business.checkin, "complete");
  assert.equal(snapshots[0].details.metrics.balance.after, null);
  assert.equal(fs.statSync(path.join(f.directory, "youzan-session.json")).mode & 0o777, 0o600);
});

test("a completed daily receipt survives another invocation without another submission", async t => {
  const f = fixture(t, {complete: true});
  const out = await f.execute({checkin: () => assert.fail("must not submit")});
  assert.equal(out.business.checkin, "complete");
  assert.deepEqual(f.calls.map(x => x.kind), ["points", "page", "points"]);
});

test("status-only reads never submit, and public activity visibility is not a daily state", async t => {
  const f = fixture(t);
  const out = await f.execute({}, {statusOnly: true});
  assert.equal(out.reason, "checkin_status_unconfirmed");
  assert.deepEqual(out.business, {checkin: "unknown", points: "complete"});
  assert.equal(f.state.action(), null);
  assert.equal(f.calls.some(x => x.kind === "checkin"), false);
});

test("the anonymous code=0 points shape neither proves login nor triggers code refresh", async t => {
  const f = fixture(t);
  const out = await f.execute({points: () => ({do_ext: false})});
  assert.equal(out.reason, "merchant_points_unconfirmed");
  assert.equal(out.execution, "failed");
  assert.equal(f.codes(), 0);
  assert.equal(f.state.session().accessToken, session.accessToken);
  assert.deepEqual(f.calls.map(x => x.kind), ["points"]);
});

test("an explicit expired session is replaced using exactly one code and one authorization", async t => {
  const f = fixture(t);
  const out = await f.execute({points: current => {
    if (current.accessToken === session.accessToken) throw new MerchantError("merchant_authentication_invalid");
    return {real_points: 0};
  }});
  assert.equal(out.business.checkin, "complete");
  assert.equal(f.codes(), 1);
  assert.equal(f.calls.filter(x => x.kind === "login").length, 1);
  assert.equal(f.state.session().accessToken, "new-token");
});

test("a cached session's network failure does not erase credentials or reauthorize", async t => {
  const f = fixture(t);
  const out = await f.execute({points: () => { throw new MerchantError("merchant_network_error"); }});
  assert.equal(out.reason, "merchant_network_error");
  assert.equal(f.codes(), 0);
  assert.equal(f.state.session().accessToken, session.accessToken);
});

test("code/client failures remain distinct from merchant login failures and leak no messages", async t => {
  const f = fixture(t, {cached: false});
  const out = await f.execute({}, {getCode: async () => { throw Error("provider disclosed a secret"); }});
  assert.equal(out.reason, "wechat_code_unavailable");
  assert.equal(JSON.stringify(out).includes("secret"), false);
  assert.deepEqual(f.calls, []);
  const rejectedCode = await f.execute({}, {getCode: async () => { throw Error("wechat_code_authentication_invalid"); }});
  assert.equal(rejectedCode.reason, "wechat_code_authentication_invalid");
  assert.deepEqual(f.calls, []);
  const merchant = await f.execute({login: () => { throw new MerchantError("merchant_authentication_invalid"); }});
  assert.equal(merchant.reason, "merchant_authentication_invalid");
  assert.equal(f.codes(), 1);
  assert.equal(f.calls.length, 1);
});

test("a failed one-use-code authorization is never repeated with a fallback body", async t => {
  const f = fixture(t, {cached: false});
  const out = await f.execute({login: () => { throw new MerchantError("merchant_network_error"); }});
  assert.equal(out.reason, "merchant_network_error");
  assert.equal(f.codes(), 1);
  assert.deepEqual(f.calls.map(x => x.kind), ["login"]);
});

test("an interrupted GET check-in preserves intent and cannot be resubmitted after restart", async t => {
  const f = fixture(t);
  const out = await f.execute({checkin: () => { throw new MerchantError("merchant_request_timeout"); }});
  assert.equal(out.business.checkin, "unknown");
  assert.equal(out.details.metrics.balance.delta, 5); // A balance change is not a check-in receipt.
  assert.equal(f.state.action().status, "pending");
  const reopened = store(f.directory, f.owner, DAY);
  const retry = await f.execute({checkin: () => assert.fail("ambiguous write must not repeat")}, {state: reopened});
  assert.equal(retry.reason, "checkin_pending_confirmation");
  assert.equal(f.calls.filter(x => x.kind === "checkin").length, 1);
});

test("empty or malformed success data does not become confirmed check-in", async t => {
  const f = fixture(t);
  const out = await f.execute({checkin: () => ({desc: "签到成功"})});
  assert.equal(out.reason, "checkin_receipt_unconfirmed");
  assert.equal(out.business.checkin, "unknown");
  assert.equal(f.state.action().status, "pending");
});

test("a readback failure preserves the independently confirmed write", async t => {
  const f = fixture(t);
  let reads = 0;
  const out = await f.execute({page: () => {
    if (++reads === 2) throw new MerchantError("merchant_network_error");
    return {checkinId: 6287727};
  }});
  assert.equal(out.execution, "failed");
  assert.equal(out.business.checkin, "complete");
  assert.equal(out.business.points, "unknown");
  assert.equal(out.details.metrics.balance.current, 100);
  assert.equal(out.details.metrics.balance.after, null);
  assert.equal(out.details.metrics.balance.delta, null);
});

test("an I/O error saving the received receipt preserves confirmation but fails execution", async t => {
  const f = fixture(t);
  const state = {...f.state, setAction(activity, status) {
    if (status === "complete") throw Error("simulated disk failure with private path");
    f.state.setAction(activity, status);
  }};
  const out = await f.execute({}, {state});
  assert.equal(out.execution, "failed");
  assert.equal(out.business.checkin, "complete");
  assert.equal(out.reason, "state_or_provider_error");
  assert.equal(f.state.action().status, "pending");
  assert.equal(JSON.stringify(out).includes("private path"), false);
});

test("an activity change does not replay a pending write against a different activity", async t => {
  const f = fixture(t, {pending: true});
  const out = await f.execute({page: () => ({checkinId: 6287728})});
  assert.equal(out.reason, "checkin_activity_changed_unconfirmed");
  assert.equal(out.business.checkin, "unknown");
  assert.equal(f.calls.some(x => x.kind === "checkin"), false);
});

test("cache bindings isolate YYB identities and business days", t => {
  const f = fixture(t, {complete: true});
  const otherOwner = binding("main", {...config.wechat, account: "account2"});
  const switched = store(f.directory, otherOwner, DAY);
  assert.equal(switched.action(), null);
  assert.equal(switched.session(), null);
  assert.equal(store(f.directory, f.owner, "2026-10-20").action(), null);
});

test("private file storage rejects readable credentials and symlinks", t => {
  const f = fixture(t);
  const file = path.join(f.directory, "input.json");
  writePrivate(file, {token: "private"});
  assert.deepEqual(readPrivate(file), {token: "private"});
  fs.chmodSync(file, 0o644);
  assert.throws(() => readPrivate(file), /private_file_invalid/);
  fs.chmodSync(file, 0o600);
  const alias = path.join(f.directory, "alias.json");
  fs.symlinkSync(file, alias);
  assert.throws(() => readPrivate(alias));
});

test("transport binds merchant, consumes code once, and merges login/session cookies", async () => {
  const calls = [];
  const request = transport("test-agent", async (url, options) => {
    calls.push({url, options});
    return new Response(JSON.stringify({code: 0, data: {...session, cookie: "a=1; b=2"}}),
      {status: 200, headers: {"Set-Cookie": "a=3; Secure; Path=/"}});
  });
  const login = await request("login", null, {code: "one-use-code"});
  assert.equal(login.cookie, "a=3; b=2");
  assert.equal(calls[0].url.origin, "https://h5.youzan.com");
  assert.equal(calls[0].options.redirect, "manual");
  assert.deepEqual(JSON.parse(calls[0].options.body), {appId: APP_ID, clientBiz: "weapp_wsc", code: "one-use-code"});
  assert.equal(calls[0].url.search, "");
  await request("checkin", {...session}, {checkinId: "6287727"});
  assert.equal(calls[1].options.method, "GET");
  assert.equal(calls[1].url.searchParams.get("app_id"), APP_ID);
  assert.equal(calls[1].url.searchParams.get("kdt_id"), KDT_ID);
  assert.equal(calls[1].url.searchParams.get("checkinId"), "6287727");
  assert.equal(calls[1].url.searchParams.get("access_token"), session.accessToken);
});

test("transport rejects redirects, HTTP authentication failure and participation-limit ambiguity", async () => {
  const attempt = response => transport("agent", async () => response)("points", {...session});
  await assert.rejects(attempt(new Response(null, {status: 302, headers: {Location: "https://elsewhere.invalid/"}})),
    {reason: "merchant_redirect_rejected"});
  await assert.rejects(attempt(new Response("private login page", {status: 401})),
    {reason: "merchant_authentication_invalid"});
  await assert.rejects(attempt(new Response(JSON.stringify({code: 111, msg: "已达最大参与次数"}))),
    {reason: "merchant_business_rejected"});
  await assert.rejects(attempt(new Response(JSON.stringify({code: 111, msg: "今日已签到"}))),
    {reason: "merchant_already_checked_in"});
});

test("transport bounds response bytes and never exposes raw errors", async () => {
  const request = transport("agent", async () => new Response("x".repeat(1024 * 1024 + 1)));
  await assert.rejects(request("page", {...session}), {reason: "merchant_response_limit"});
  const failed = transport("agent", async () => { throw Error("https://private-token@secret.invalid/"); });
  await assert.rejects(failed("page", {...session}), error => {
    assert.equal(error.message, "merchant_network_error");
    return true;
  });
});

test("session and configuration parsing retain only necessary fields", () => {
  assert.deepEqual(sessionValue({access_token: "token", mobile: "private", nickname: "private"}),
    {accessToken: "token", sessionId: "", cookie: "", kdtId: KDT_ID});
  assert.throws(() => sessionValue({...session, kdtId: "another-shop"}), /merchant_login_response_invalid/);
  assert.throws(() => configValue({wechat: {...config.wechat, url: "not a url"}}), /configuration_invalid/);
  assert.throws(() => configValue({wechat: {...config.wechat, url: "http://user:password@localhost"}}), /configuration_invalid/);
});
