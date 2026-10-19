"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const {spawnSync} = require("node:child_process");
const {APP_ID, BASE_URL, ENDPOINTS, RESPONSE_LIMIT, readConfig, transport, execute} =
  require("../platforms/ole/adapter.cjs");
const {OleError, State, configurationIdentity} = require("../platforms/ole/state.cjs");
const {validateDetails} = require("../common/details.cjs");

const DAY = "2026-10-19";
const config = () => ({wechat: {url: "http://127.0.0.1:8000", token: "synthetic-yyb-token",
  account: "yyb-account-ref"}, shop_code: "real-account-shop"});
const session = () => ({session_id: "synthetic-merchant-session", openid: "merchant-openid",
  shop_code: null});
const ok = (data) => ({httpStatus: 200, payload: {state_code: 200, data}});
const status = (signed, points = 100, extra = {}) => ok({sign_of_day: signed ? "Y" : "N",
  total_integral: points, ...extra});

function fixture(t, {cached = true, date = DAY, configuration = config()} = {}) {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "ole-checkin-"));
  t.after(() => fs.rmSync(directory, {recursive: true, force: true}));
  const state = new State(directory, "test", date, configurationIdentity(configuration.wechat));
  if (cached) state.saveSession(session());
  return {directory, state, config: configuration};
}

function requests(steps) {
  const calls = [];
  const request = async (method, endpoint, body, auth) => {
    const step = steps.shift();
    calls.push({method, endpoint, body, auth});
    assert.ok(step, "unexpected merchant request");
    assert.equal(method, step[0]);
    assert.equal(endpoint, step[1]);
    if (step[2] instanceof Error) throw step[2];
    return step[2];
  };
  return {calls, request, done: () => assert.equal(steps.length, 0)};
}

async function run(fixture, scenario, getCode = async () => {
  assert.fail("cached session must not call the code service");
}) {
  const result = await execute({...fixture, request: scenario.request, getCode});
  scenario.done();
  validateDetails(result.details);
  return result;
}

test("today already signed uses one query without code, store lookup or submission", async (t) => {
  const f = fixture(t), s = requests([["GET", ENDPOINTS.sign, status(true, 123)]]);
  const out = await run(f, s);
  assert.deepEqual(out.business, {checkin: "complete", balance: "complete"});
  assert.equal(out.reason, "already_complete");
  assert.equal(out.details.metrics.balance.current, 123);
  assert.equal(out.details.metrics.balance.delta, null);
  assert.equal(f.state.checkin, "complete");
});

test("login keeps merchant identity separate from YYB reference, writes once and reads back", async (t) => {
  const f = fixture(t, {cached: false});
  const s = requests([
    ["POST", ENDPOINTS.login, ok({user_session: "new-session", open_id: "actual-merchant-openid"})],
    ["GET", ENDPOINTS.sign, status(false, "100")],
    ["POST", ENDPOINTS.sign, ok({integral: 5})],
    ["GET", ENDPOINTS.sign, status(true, "105")],
  ]);
  let codes = 0;
  const out = await run(f, s, async (credentials, appid) => {
    codes++;
    assert.equal(credentials.account, "yyb-account-ref");
    assert.equal(appid, APP_ID);
    return "one-time-code";
  });
  assert.equal(codes, 1);
  assert.deepEqual(s.calls[0].body, {code: "one-time-code"});
  assert.equal(s.calls[0].auth, null);
  assert.equal(s.calls[2].auth.openid, "actual-merchant-openid");
  assert.deepEqual(s.calls[2].body, {enter_shop_code: "real-account-shop"});
  assert.equal(out.reason, "checkin_confirmed");
  assert.deepEqual(out.details.metrics.balance,
    {unit: "points", current: 105, max: null, before: 100, after: 105, delta: 5});
  const saved = JSON.parse(fs.readFileSync(path.join(f.directory, "ole-state.json")));
  assert.equal(saved.session.openid, "actual-merchant-openid");
  assert.equal(JSON.stringify(saved).includes("one-time-code"), false);
});

test("explicit user position resolves the merchant store without an author coordinate", async (t) => {
  const configuration = config();
  delete configuration.shop_code;
  configuration.location = "121.5,31.2";
  const f = fixture(t, {configuration});
  const s = requests([
    ["GET", ENDPOINTS.sign, status(false)],
    ["POST", ENDPOINTS.shop, ok({shop_code: "near-user-shop"})],
    ["POST", ENDPOINTS.sign, ok({})],
    ["GET", ENDPOINTS.sign, status(true)],
  ]);
  await run(f, s);
  assert.equal(s.calls[1].body.location, "121.5,31.2");
  assert.deepEqual(s.calls[2].body, {enter_shop_code: "near-user-shop"});
});

test("a store returned by the authenticated status needs no location lookup", async (t) => {
  const configuration = config();
  delete configuration.shop_code;
  const f = fixture(t, {configuration});
  const s = requests([
    ["GET", ENDPOINTS.sign, status(false, 100, {shop_code: "member-store"})],
    ["POST", ENDPOINTS.sign, ok({})],
    ["GET", ENDPOINTS.sign, status(true, 102)],
  ]);
  assert.equal((await run(f, s)).business.checkin, "complete");
  assert.equal(s.calls[1].body.enter_shop_code, "member-store");
});

test("missing store is explicit and no intent or submission is made", async (t) => {
  const configuration = config();
  delete configuration.shop_code;
  const f = fixture(t, {configuration});
  const out = await run(f, requests([["GET", ENDPOINTS.sign, status(false)]]));
  assert.equal(out.reason, "missing_shop_configuration");
  assert.deepEqual(out.business, {checkin: "blocked", balance: "complete"});
  assert.equal(f.state.checkin, "unknown");
});

test("unknown daily status does not authorize a sign request", async (t) => {
  const f = fixture(t);
  const out = await run(f, requests([["GET", ENDPOINTS.sign, ok({total_integral: 100})]]));
  assert.equal(out.reason, "checkin_status_unconfirmed");
  assert.equal(out.business.checkin, "unknown");
});

test("explicitly unregistered member is distinguished from missing login fields", async (t) => {
  const first = fixture(t, {cached: false});
  const out = await run(first, requests([["POST", ENDPOINTS.login,
    ok({member_id: null, inquire: "N"})]]), async () => "code");
  assert.equal(out.reason, "membership_registration_required");
  assert.equal(out.business.checkin, "blocked");
  const second = fixture(t, {cached: false});
  const malformed = await run(second, requests([["POST", ENDPOINTS.login, ok({})]]), async () => "code");
  assert.equal(malformed.reason, "merchant_login_response_invalid");
});

test("expired cached merchant session refreshes once then rechecks status", async (t) => {
  const f = fixture(t);
  const s = requests([
    ["GET", ENDPOINTS.sign, {httpStatus: 200, payload: {state_code: 401}}],
    ["POST", ENDPOINTS.login, ok({user_session: "fresh-session", open_id: "merchant-openid"})],
    ["GET", ENDPOINTS.sign, status(true)],
  ]);
  let refreshed = 0;
  const out = await run(f, s, async () => { refreshed++; return "new-code"; });
  assert.equal(refreshed, 1);
  assert.equal(out.business.checkin, "complete");
  assert.equal(s.calls[2].auth.session_id, "fresh-session");
});

test("network failures do not invalidate a cached session or cause code refresh", async (t) => {
  const f = fixture(t), out = await run(f,
    requests([["GET", ENDPOINTS.sign, new OleError("merchant_network_error")]]));
  assert.equal(out.reason, "merchant_network_error");
  assert.equal(f.state.session.session_id, "synthetic-merchant-session");
});

test("the durable pending intent exists before POST and a lost response can reconcile", async (t) => {
  const f = fixture(t);
  let posts = 0;
  const out = await execute({...f, getCode: async () => assert.fail("no refresh expected"),
    request: async (method, endpoint) => {
      assert.equal(endpoint, ENDPOINTS.sign);
      if (method === "POST") {
        posts++;
        const saved = JSON.parse(fs.readFileSync(path.join(f.directory, "ole-state.json")));
        assert.deepEqual(saved.intent, {date: DAY, status: "pending"});
        throw new OleError("merchant_timeout");
      }
      return status(posts > 0, posts ? 103 : 100);
    }});
  assert.equal(posts, 1);
  assert.equal(out.business.checkin, "complete");
  assert.equal(out.details.metrics.balance.delta, 3);
});

test("successful POST cannot hide failed readback or invent an after balance", async (t) => {
  const f = fixture(t);
  const out = await run(f, requests([
    ["GET", ENDPOINTS.sign, status(false, 100)],
    ["POST", ENDPOINTS.sign, ok({total_integral: 999, integral: 899})],
    ["GET", ENDPOINTS.sign, new OleError("merchant_timeout")],
  ]));
  assert.equal(out.business.checkin, "unknown");
  assert.equal(out.business.balance, "unknown");
  assert.equal(out.reason, "merchant_timeout");
  assert.deepEqual(out.details.metrics.balance,
    {unit: "points", current: 100, max: null, before: 100, after: null, delta: null});
  assert.equal(f.state.checkin, "pending");
});

test("persisted pending recovery performs only GET and later confirms without replay", async (t) => {
  const f = fixture(t);
  const first = await run(f, requests([
    ["GET", ENDPOINTS.sign, status(false)],
    ["POST", ENDPOINTS.sign, new OleError("merchant_timeout")],
    ["GET", ENDPOINTS.sign, status(false)],
  ]));
  assert.equal(first.business.checkin, "unknown");
  const reload = () => new State(f.directory, "test", DAY, configurationIdentity(f.config.wechat));
  const next = await run({...f, state: reload()},
    requests([["GET", ENDPOINTS.sign, status(false)]]));
  assert.equal(next.reason, "write_pending_confirmation");
  const confirmed = await run({...f, state: reload()},
    requests([["GET", ENDPOINTS.sign, status(true, 104)]]));
  assert.equal(confirmed.business.checkin, "complete");
});

test("a read failure preserves a same-day confirmed sign but a contradictory status never repeats it", async (t) => {
  const f = fixture(t);
  f.state.record("complete");
  const failed = await run(f,
    requests([["GET", ENDPOINTS.sign, new OleError("merchant_timeout")]]));
  assert.equal(failed.business.checkin, "complete");
  assert.equal(failed.business.balance, "unknown");
  const conflict = await run(f, requests([["GET", ENDPOINTS.sign, status(false)]]));
  assert.equal(conflict.reason, "checkin_state_conflict");
  assert.equal(conflict.business.checkin, "unknown");
});

test("a new business day allows a new sign after yesterday's pending action", async (t) => {
  const f = fixture(t);
  f.state.record("pending");
  const next = new State(f.directory, "test", "2026-10-20", configurationIdentity(f.config.wechat));
  const out = await run({...f, state: next}, requests([
    ["GET", ENDPOINTS.sign, status(false)],
    ["POST", ENDPOINTS.sign, ok({})],
    ["GET", ENDPOINTS.sign, status(true, 105)],
  ]));
  assert.equal(out.business.checkin, "complete");
});

test("missing or invalid balance stays unknown even if the sign is confirmed", async (t) => {
  for (const balance of [null, -1, true, "", "not-a-number"]) {
    const f = fixture(t);
    const out = await run(f, requests([["GET", ENDPOINTS.sign, status(true, balance)]]));
    assert.equal(out.business.checkin, "complete");
    assert.equal(out.business.balance, "unknown");
    assert.equal(out.details.metrics.balance.current, null);
  }
});

test("YYB failures have a fixed reason and never leak code service exception text", async (t) => {
  const f = fixture(t, {cached: false}), s = requests([]);
  const out = await run(f, s, async () => { throw Error("sensitive-token-in-upstream-error"); });
  assert.equal(out.reason, "wechat_code_unavailable");
  assert.equal(JSON.stringify(out).includes("sensitive"), false);
});

test("shared YYB client's fixed authentication and account errors remain distinguishable", async (t) => {
  for (const reason of ["wechat_code_authentication_invalid", "wechat_code_account_unavailable",
    "wechat_code_connection_failed", "wechat_code_timeout"]) {
    const f = fixture(t, {cached: false});
    const out = await run(f, requests([]), async () => { throw Error(reason); });
    assert.equal(out.reason, reason);
    assert.equal(out.business.checkin, "unknown");
  }
});

test("fresh credentials rejected by the merchant are not refreshed in a login loop", async (t) => {
  const f = fixture(t, {cached: false});
  let codes = 0;
  const out = await run(f, requests([
    ["POST", ENDPOINTS.login, ok({user_session: "new-session", open_id: "merchant-openid"})],
    ["GET", ENDPOINTS.sign, {httpStatus: 200, payload: {state_code: 401}}],
  ]), async () => { codes++; return "code"; });
  assert.equal(codes, 1);
  assert.equal(out.reason, "authentication_invalid");
});

test("session expiry after submission permits only refreshed readback, never another POST", async (t) => {
  const f = fixture(t);
  const s = requests([
    ["GET", ENDPOINTS.sign, status(false)],
    ["POST", ENDPOINTS.sign, new OleError("merchant_timeout")],
    ["GET", ENDPOINTS.sign, {httpStatus: 200, payload: {state_code: 401}}],
    ["POST", ENDPOINTS.login, ok({user_session: "fresh-session", open_id: "merchant-openid"})],
    ["GET", ENDPOINTS.sign, status(true, 106)],
  ]);
  const out = await run(f, s, async () => "fresh-code");
  assert.equal(s.calls.filter(x => x.method === "POST" && x.endpoint === ENDPOINTS.sign).length, 1);
  assert.equal(out.business.checkin, "complete");
});

test("state is private and cannot be reused for a different YYB account reference", (t) => {
  const f = fixture(t), file = path.join(f.directory, "ole-state.json");
  assert.equal(fs.statSync(file).mode & 0o777, 0o600);
  const changed = {...f.config.wechat, account: "another-ref"};
  assert.throws(() => new State(f.directory, "test", DAY, configurationIdentity(changed)),
    {code: "account_configuration_mismatch"});
  fs.chmodSync(file, 0o644);
  assert.throws(() => new State(f.directory, "test", DAY, configurationIdentity(f.config.wechat)),
    {code: "invalid_action_state"});
});

test("configuration requires a private file and validates coordinates without providing a default", (t) => {
  const f = fixture(t), file = path.join(f.directory, "config.json");
  fs.writeFileSync(file, JSON.stringify(config()), {mode: 0o600});
  assert.equal(readConfig(file).location, undefined);
  fs.chmodSync(file, 0o644);
  assert.throws(() => readConfig(file), {code: "invalid_private_configuration"});
  fs.chmodSync(file, 0o600);
  fs.writeFileSync(file, JSON.stringify({...config(), location: "181,31"}));
  assert.throws(() => readConfig(file), {code: "invalid_configuration"});
});

test("merchant HTTP stays on the fixed source with exact business identity and no redirect", async () => {
  let calls = 0;
  const request = transport(config(), async (url, options) => {
    calls++;
    assert.equal(url, BASE_URL + ENDPOINTS.sign);
    assert.equal(options.redirect, "manual");
    assert.equal(options.headers.sessionId, "synthetic-merchant-session");
    assert.equal(options.headers.oleWxOpenId, "merchant-openid");
    assert.equal(options.body, undefined);
    return new Response("redirect with secret", {status: 302, headers: {Location: "https://example.invalid"}});
  });
  await assert.rejects(request("GET", ENDPOINTS.sign, null, session()),
    {code: "merchant_redirect_rejected"});
  assert.equal(calls, 1);
});

test("merchant responses are bounded before JSON parsing", async () => {
  const request = transport(config(), async () => new Response("x".repeat(RESPONSE_LIMIT + 1)));
  await assert.rejects(request("GET", ENDPOINTS.sign, null, session()),
    {code: "merchant_response_limit"});
});

test("public main can run cached-session HTTP through the actual result publisher without YYB installed", (t) => {
  const f = fixture(t), file = path.join(f.directory, "config.json"), result = path.join(f.directory, "result.json");
  fs.writeFileSync(file, JSON.stringify(f.config), {mode: 0o600});
  const adapter = path.resolve(__dirname, "../platforms/ole/adapter.cjs");
  const child = spawnSync(process.execPath, ["-e", `
    global.fetch=async()=>new Response(JSON.stringify({state_code:200,data:{sign_of_day:'Y',total_integral:122}}));
    require(${JSON.stringify(adapter)}).main();
  `], {env: {PATH: process.env.PATH, OLE_CONFIG: file, BENEFITS_STATE_DIR: f.directory,
    BENEFITS_ACCOUNT: "test", BENEFITS_BUSINESS_DATE: DAY, BENEFITS_RUN_ID: "public-main",
    BENEFITS_PLATFORM: "ole", BENEFITS_RESULT_PATH: result}, encoding: "utf8", timeout: 5000});
  assert.equal(child.status, 0, child.stderr);
  const out = JSON.parse(fs.readFileSync(result));
  assert.equal(out.business.checkin, "complete");
  assert.equal(out.details.metrics.balance.current, 122);
  assert.equal(child.stdout, "");
  assert.equal(child.stderr, "");
});

test("separate public-main processes recover a lost POST response without submitting twice", (t) => {
  const f = fixture(t), file = path.join(f.directory, "config.json");
  fs.writeFileSync(file, JSON.stringify(f.config), {mode: 0o600});
  const adapter = path.resolve(__dirname, "../platforms/ole/adapter.cjs");
  function invoke(finalSigned, permitPost) {
    const result = path.join(f.directory, "result.json");
    const child = spawnSync(process.execPath, ["-e", `
      const calls=[];
      global.fetch=async(url,options)=>{
        calls.push(options.method);
        if(options.method==='POST') {
          if(!${permitPost}) throw Error('unexpected duplicate POST');
          throw Error('connection lost after submission');
        }
        return new Response(JSON.stringify({state_code:200,data:{
          sign_of_day:${JSON.stringify(finalSigned ? "Y" : "N")},total_integral:100}}));
      };
      require(${JSON.stringify(adapter)}).main().then(()=>process.stdout.write(JSON.stringify(calls)));
    `], {env: {PATH: process.env.PATH, OLE_CONFIG: file, BENEFITS_STATE_DIR: f.directory,
      BENEFITS_ACCOUNT: "test", BENEFITS_BUSINESS_DATE: DAY, BENEFITS_RUN_ID: "recovery-main",
      BENEFITS_PLATFORM: "ole", BENEFITS_RESULT_PATH: result}, encoding: "utf8", timeout: 5000});
    assert.ok([0, 1].includes(child.status), child.stderr);
    return {calls: JSON.parse(child.stdout), result: JSON.parse(fs.readFileSync(result))};
  }
  const first = invoke(false, true);
  assert.deepEqual(first.calls, ["GET", "POST", "GET"]);
  assert.equal(first.result.business.checkin, "unknown");
  const second = invoke(false, false);
  assert.deepEqual(second.calls, ["GET"]);
  assert.equal(second.result.reason, "write_pending_confirmation");
  const third = invoke(true, false);
  assert.deepEqual(third.calls, ["GET"]);
  assert.equal(third.result.business.checkin, "complete");
});
