"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const client = require("../platforms/wetalk/adapter.cjs");
const { journal } = require("../platforms/wetalk/state.cjs");

const day = "2026-10-19", identity = "a".repeat(64);
const config = () => client.configuration({
  params: { email: "fixture+tag@example.test", device: "a+b%2F", empty: "", sign: "old", signDate: "old" },
  headers: { "User-Agent": "WeTalk fixture", Authorization: "Bearer synthetic-secret" },
});
const memory = () => journal(null, "account1", day, identity);
const response = result => ({ httpStatus: 200, payload: { retcode: 0, result } });
const eligible = balance => response({ balance, isallowcheckin: true });
const completed = balance => response({ balance, isallowcheckin: false, notallowcheckinreason: "今日已签到" });
function temporary(t) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "wetalk-test-"));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  return root;
}
function scripted(rows) {
  const calls = [];
  return { calls, request: async action => {
    calls.push(action);
    const row = rows.shift();
    assert.ok(row, "unexpected additional request");
    if (row instanceof Error) throw row;
    return row;
  } };
}

test("signature matches the pinned upstream ASCII vector and preserves decoded percent/plus values", () => {
  const params = config().params;
  const date = new Date("2026-10-19T08:00:00+08:00");
  assert.equal(client.signedParams(params, date).sign, "b31c98c1a686d8e0ae7707a1a97c16c7");
  assert.equal(client.requestUrl("checkIn", params, date),
    "https://api.wetalkapp.com/app/checkIn?device=a%2Bb%252F&email=fixture%2Btag%40example.test" +
    "&empty=&sign=b31c98c1a686d8e0ae7707a1a97c16c7&signDate=2026-10-19%2000%3A00%3A00");
  assert.equal(client.signedParams({ ...params, sign: "replaced", signDate: "yesterday" }, date).sign,
    "b31c98c1a686d8e0ae7707a1a97c16c7");
});

test("signature ordering is independent of JSON order and UTC crosses the local date boundary", () => {
  const now = new Date("2026-10-19T01:30:00+08:00");
  assert.equal(client.signedParams({ z: "z", email: "f@example.test" }, now).sign,
    client.signedParams({ email: "f@example.test", z: "z" }, now).sign);
  assert.equal(client.signedParams(config().params, now).signDate, "2026-10-18 17:30:00");
  assert.equal(client.configuration({ params: { email: "f@example.test", _: "captured-cache-key" } }).params._,
    "captured-cache-key");
});

test("non-ASCII signing inputs fail explicitly instead of changing the upstream encoding", () => {
  assert.throws(() => client.configuration({ params: { email: "f@example.test", device: "中文" } }),
    error => error.reason === "signature_parameters_unsupported");
  assert.throws(() => client.requestUrl("videoBonus", config().params),
    error => error.reason === "invalid_configuration");
});

test("captured transport headers cannot change the target while actual authentication headers survive", () => {
  const parsed = client.configuration({ params: { email: "f@example.test" }, headers: {
    Host: "other.invalid", ":authority": "other.invalid", "Proxy-Authorization": "proxy-secret",
    "Content-Length": "9000", Connection: "keep-alive", "Accept-Encoding": "br",
    Cookie: "session=synthetic", "User-Agent": "original", Authorization: "original-token",
  } });
  assert.deepEqual({ ...parsed.headers }, {
    cookie: "session=synthetic", "user-agent": "original", authorization: "original-token", accept: "application/json",
  });
  assert.throws(() => client.configuration({ params: { email: "x" }, headers: { Cookie: "a", cookie: "b" } }));
  assert.throws(() => client.configuration({ params: { email: "x" }, headers: { "User-Agent": "bad\r\nInjected: yes" } }));
});

test("private config is bounded, regular, owner-private and never accepts a raw request URL", t => {
  const root = temporary(t), file = path.join(root, "config.json");
  fs.writeFileSync(file, JSON.stringify({ params: { email: "f@example.test" } }), { mode: 0o600 });
  assert.equal(client.loadConfig(file).params.email, "f@example.test");
  fs.chmodSync(file, 0o644);
  assert.throws(() => client.loadConfig(file), error => error.reason === "private_configuration_unreadable");
  fs.chmodSync(file, 0o600);
  fs.writeFileSync(file, " ".repeat(16385));
  assert.throws(() => client.loadConfig(file), error => error.reason === "invalid_configuration");
  assert.throws(() => client.configuration({ url: "https://api.wetalkapp.com/app/checkIn?secret=x", params: {} }));
  assert.throws(() => client.loadConfig("relative.json"), error => error.reason === "invalid_configuration");
});

test("only an explicit already-signed reason confirms a forbidden check-in", async () => {
  const done = scripted([completed("12.5")]);
  const result = await client.run(done.request, memory());
  assert.equal(result.business.checkin, "complete");
  assert.equal(result.business.balance, "complete");
  assert.equal(result.details.metrics.reward.current, null);
  assert.equal(result.details.metrics.balance.current, 12.5);
  assert.equal(result.details.metrics.balance.delta, null);
  assert.deepEqual(done.calls, ["queryBalanceAndBonus"]);

  const blocked = scripted([response({ balance: 12.5, isallowcheckin: false, notallowcheckinreason: "当前不可领取" })]);
  const unavailable = await client.run(blocked.request, memory());
  assert.equal(unavailable.business.checkin, "blocked");
  assert.equal(unavailable.reason, "checkin_unavailable");
  assert.deepEqual(blocked.calls, ["queryBalanceAndBonus"]);
});

test("unknown eligibility and read-only mode never submit", async () => {
  for (const value of [undefined, "true", 1]) {
    const fake = scripted([response({ balance: 2, isallowcheckin: value })]);
    assert.equal((await client.run(fake.request, memory())).business.checkin, "unknown");
    assert.equal(fake.calls.length, 1);
  }
  const fake = scripted([eligible(0)]), state = memory();
  const result = await client.run(fake.request, state, { statusOnly: true });
  assert.equal(result.business.checkin, "incomplete");
  assert.equal(result.details.metrics.balance.current, 0);
  assert.equal(state.status, "unknown");
  assert.equal(fake.calls.length, 1);
});

test("a fresh sign-in persists intent before writing and reads actual reward and balance", async t => {
  const root = temporary(t), state = journal(root, "account1", day, identity);
  const calls = [];
  const request = async action => {
    calls.push(action);
    if (calls.length === 1) return eligible(0);
    if (action === "checkIn") {
      assert.equal(JSON.parse(fs.readFileSync(path.join(root, "checkin.json"))).checkin, "pending");
      return response({ bonus: "0.2", bonusHint: "ignored untrusted text" });
    }
    return completed("0.2");
  };
  const result = await client.run(request, state);
  assert.equal(result.execution, "ok");
  assert.deepEqual(result.business, { checkin: "complete", balance: "complete" });
  assert.equal(result.details.metrics.reward.current, 0.2);
  assert.equal(result.details.metrics.balance.delta, 0.2);
  assert.deepEqual(calls, ["queryBalanceAndBonus", "checkIn", "queryBalanceAndBonus"]);
  const saved = journal(root, "account1", day, identity);
  assert.equal(saved.status, "complete");
  assert.equal(saved.reward, 0.2);
  assert.equal(fs.statSync(path.join(root, "checkin.json")).mode & 0o777, 0o600);
  assert.equal(fs.readFileSync(path.join(root, "checkin.json"), "utf8").includes("example.test"), false);
});

test("a lost write response is recovered by readback without repeating checkIn", async () => {
  const fake = scripted([eligible(1), new Error("request URL contained a secret"), completed(2)]);
  const state = memory(), result = await client.run(fake.request, state);
  assert.equal(result.reason, "checkin_recovered");
  assert.equal(result.business.checkin, "complete");
  assert.equal(result.details.metrics.reward.current, null);
  assert.equal(state.status, "complete");
  assert.equal(fake.calls.filter(x => x === "checkIn").length, 1);
});

test("intent persistence failure prevents writing but cannot erase a signed status already read", async t => {
  const first = temporary(t), second = temporary(t);
  const open = fs.openSync.bind(fs);
  t.mock.method(fs, "openSync", (file, ...args) => {
    if (String(file).includes(".tmp-")) throw new Error("simulated full filesystem");
    return open(file, ...args);
  });
  const eligibleRead = scripted([eligible(1)]);
  const denied = await client.run(eligibleRead.request, journal(first, "account1", day, identity));
  assert.equal(denied.reason, "action_state_io_error");
  assert.equal(denied.business.checkin, "unknown");
  assert.deepEqual(eligibleRead.calls, ["queryBalanceAndBonus"]);
  const signedRead = scripted([completed(2)]);
  const confirmed = await client.run(signedRead.request, journal(second, "account1", day, identity));
  assert.equal(confirmed.reason, "action_state_io_error");
  assert.equal(confirmed.business.checkin, "complete");
});

test("an ambiguous write remains read-only across invocations, then recovers from a signed status", async t => {
  const root = temporary(t);
  const first = scripted([eligible(1), new Error("lost"), eligible(1)]);
  const firstResult = await client.run(first.request, journal(root, "account1", day, identity));
  assert.equal(firstResult.reason, "write_pending_confirmation");
  assert.equal(firstResult.business.checkin, "unknown");
  const next = scripted([eligible(1)]);
  assert.equal((await client.run(next.request, journal(root, "account1", day, identity))).reason,
    "write_pending_confirmation");
  assert.deepEqual(next.calls, ["queryBalanceAndBonus"]);
  const later = scripted([completed(2)]);
  assert.equal((await client.run(later.request, journal(root, "account1", day, identity))).business.checkin,
    "complete");
});

test("an HTTP 200 malformed check-in is not a receipt, and a false state without explanation is not recovery", async () => {
  const fake = scripted([eligible(1), { httpStatus: 200, payload: {} },
    response({ balance: 1, isallowcheckin: false })]);
  const result = await client.run(fake.request, memory());
  assert.equal(result.business.checkin, "unknown");
  assert.equal(result.reason, "write_pending_confirmation");
});

test("an acknowledged sign-in survives a failed balance readback and is never submitted again", async t => {
  const root = temporary(t);
  const first = scripted([eligible(2), response({ bonus: 1 }), new Error("private URL in raw failure")]);
  const output = await client.run(first.request, journal(root, "account1", day, identity));
  assert.equal(output.execution, "failed");
  assert.deepEqual(output.business, { checkin: "complete", balance: "unknown" });
  assert.deepEqual(output.details.metrics.balance,
    { unit: "coins", current: 2, max: null, before: 2, after: null, delta: null });
  const next = scripted([completed(3)]);
  const recovered = await client.run(next.request, journal(root, "account1", day, identity));
  assert.equal(recovered.business.checkin, "complete");
  assert.equal(recovered.details.metrics.reward.current, 1);
  assert.deepEqual(next.calls, ["queryBalanceAndBonus"]);
  assert.equal(JSON.stringify(output).includes("private URL"), false);
});

test("an explicit checkIn business receipt does not require a reported bonus", async () => {
  const fake = scripted([eligible(2), { httpStatus: 200, payload: { retcode: 0 } }, new Error("readback lost")]);
  const state = memory(), output = await client.run(fake.request, state);
  assert.equal(output.business.checkin, "complete");
  assert.equal(output.business.balance, "unknown");
  assert.equal(output.details.metrics.reward.current, null);
  assert.equal(state.status, "complete");
});

test("a conflicting live eligibility never revokes the receipt or sends a second write", async () => {
  const state = memory(), fake = scripted([eligible(1), response({ bonus: 1 }), eligible(2)]);
  const output = await client.run(fake.request, state);
  assert.equal(output.reason, "checkin_readback_conflict");
  assert.equal(output.execution, "failed");
  assert.equal(output.business.checkin, "complete");
  const next = scripted([eligible(2)]);
  assert.equal((await client.run(next.request, state)).reason, "checkin_readback_conflict");
  assert.equal(next.calls.length, 1);
});

test("authentication and signature errors stay distinct and never expose upstream messages", async () => {
  for (const [message, reason] of [["登录已失效 secret-token", "authentication_invalid"],
    ["签名错误: secret-token", "signature_invalid"]]) {
    const fake = scripted([{ httpStatus: 200, payload: { retcode: 1001, retmsg: message } }]);
    const output = await client.run(fake.request, memory());
    assert.equal(output.reason, reason);
    assert.equal(fake.calls.length, 1);
    assert.equal(JSON.stringify(output).includes("secret-token"), false);
  }
});

test("the live missing-client-parameters response is distinct from a rejected check-in", async () => {
  const fake = scripted([{ httpStatus: 200, payload: {
    retcode: 100004, retmsg: "Missing param or param error.", result: {},
  } }]);
  const output = await client.run(fake.request, memory());
  assert.equal(output.reason, "request_parameters_invalid");
  assert.equal(output.execution, "failed");
  assert.deepEqual(output.business, { checkin: "unknown", balance: "unknown" });
  assert.deepEqual(fake.calls, ["queryBalanceAndBonus"]);
  assert.equal(client.rejection({ httpStatus: 200, payload: {
    retcode: 100004, retmsg: "some different unverified condition", result: {},
  } }), "checkin_rejected");
});

test("an explicit missing-parameters write rejection can be corrected after a fresh eligibility query", async () => {
  const state = memory();
  const fake = scripted([eligible(1), { httpStatus: 200, payload: {
    retcode: 100004, retmsg: "Missing param or param error.", result: {},
  } }]);
  const output = await client.run(fake.request, state);
  assert.equal(output.reason, "request_parameters_invalid");
  assert.equal(state.status, "unknown");
  assert.equal(fake.calls.length, 2);
});

test("a definite write rejection does not leave an ambiguous intent blocking corrected credentials", async () => {
  const state = memory();
  const fake = scripted([eligible(1), { httpStatus: 200, payload: { retcode: 1001, retmsg: "invalid signature" } }]);
  const output = await client.run(fake.request, state);
  assert.equal(output.reason, "signature_invalid");
  assert.equal(state.status, "unknown");
  assert.equal(fake.calls.length, 2);
});

test("missing, invalid or negative balances remain null rather than becoming zero", async () => {
  for (const value of [undefined, null, false, "", "invalid", -1]) {
    const fake = scripted([completed(value)]);
    const output = await client.run(fake.request, memory());
    assert.equal(output.business.checkin, "complete");
    assert.equal(output.business.balance, "unknown");
    assert.equal(output.details.metrics.balance.current, null);
  }
});

test("account binding and corrupt journals cannot authorize a new write; a new business day resets daily facts", t => {
  const root = temporary(t), file = path.join(root, "checkin.json");
  journal(root, "account1", day, identity).set("complete", 2);
  assert.throws(() => journal(root, "account1", day, "b".repeat(64)),
    error => error.reason === "account_identity_mismatch");
  const tomorrow = journal(root, "account1", "2026-10-20", identity);
  assert.equal(tomorrow.status, "unknown");
  assert.equal(tomorrow.reward, null);
  fs.writeFileSync(file, "bad state");
  assert.throws(() => journal(root, "account1", day, identity), error => error.reason === "invalid_action_state");
});

test("transport uses only the fixed API, re-signs per request and does not follow redirects", async () => {
  let options, url, count = 0;
  const request = client.transport(config(), async (target, settings) => {
    count++; url = target; options = settings;
    return new Response(null, { status: 302, headers: { Location: "https://other.invalid/" } });
  }, () => new Date("2026-10-19T00:00:00Z"));
  const result = await request("checkIn");
  assert.equal(result.httpStatus, 302);
  assert.equal(client.rejection(result), "unexpected_redirect");
  assert.equal(options.redirect, "manual");
  assert.equal(options.method, "GET");
  assert.equal(count, 1);
  assert.equal(new URL(url).origin, "https://api.wetalkapp.com");
});

test("transport caps decoded response bodies and does not reinterpret HTML as success", async () => {
  const huge = client.transport(config(), async () => new Response("x".repeat(1048577)));
  await assert.rejects(huge("queryBalanceAndBonus"), error => error.reason === "response_limit");
  const html = client.transport(config(), async () => new Response("<html>Sign in</html>"));
  await assert.rejects(html("queryBalanceAndBonus"), error => error.reason === "invalid_provider_response");
});

test("transport times out pending I/O without leaking the URL from native errors", async t => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const request = client.transport(config(), async (url, { signal }) => new Promise((resolve, reject) => {
    signal.addEventListener("abort", () => reject(new Error("private URL: " + url)));
  }));
  const pending = request("checkIn");
  t.mock.timers.tick(30000);
  await assert.rejects(pending, error => error.reason === "request_timeout" && !error.message.includes("@"));
});

test("protocol errors and access restrictions are distinct from an authenticated success", () => {
  assert.equal(client.rejection({ httpStatus: 403 }), "access_denied");
  assert.equal(client.rejection({ httpStatus: 429 }), "rate_limited");
  assert.equal(client.rejection({ httpStatus: 503 }), "provider_unavailable");
  assert.throws(() => client.snapshot({ httpStatus: 200, payload: { retcode: "0", result: {} } }),
    error => error.reason === "invalid_provider_response");
});
