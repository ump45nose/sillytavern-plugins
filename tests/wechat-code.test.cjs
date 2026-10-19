"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const http = require("node:http");
const {getCode} = require("../common/wechat_code.cjs");

const APPID = "wx92782ef90ebc836d";
const TOKEN = "synthetic-private-token";
const ACCOUNT = "synthetic-account";
function success(code = "synthetic-code") {
  return {code: 0, msg: "success", data: {
    openid: "private-openid", account: {id: 1, nickname: "private-name"},
    result: {code, errMsg: "login:ok"},
  }};
}
async function serverFor(t, handler) {
  const server = http.createServer(handler);
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  t.after(() => new Promise((resolve) => {
    server.closeAllConnections();
    server.close(resolve);
  }));
  return {server, config: {url: "http://127.0.0.1:" + server.address().port,
    token: TOKEN, account: ACCOUNT}};
}

test("posts the pinned YYB contract and returns only its code", async (t) => {
  const requests = [];
  const {config} = await serverFor(t, (req, res) => {
    const chunks = [];
    req.on("data", (chunk) => chunks.push(chunk));
    req.on("end", () => {
      requests.push({url: req.url, method: req.method, headers: req.headers,
        body: JSON.parse(Buffer.concat(chunks))});
      res.setHeader("Content-Type", "application/json");
      res.end(JSON.stringify(success("code-" + requests.length)));
    });
  });
  config.url += "/private-prefix/";
  assert.equal(await getCode(config, APPID), "code-1");
  assert.equal(await getCode(config, APPID), "code-2");
  assert.equal(requests.length, 2, "each explicit call obtains a fresh code");
  for (const request of requests) {
    assert.equal(request.method, "POST");
    assert.equal(request.url, "/private-prefix/wxapp/getCode");
    assert.equal(request.headers.authorization, "Bearer " + TOKEN);
    assert.equal(request.headers["content-type"], "application/json");
    assert.deepEqual(request.body, {ref: ACCOUNT, app_id: APPID});
    assert.equal(request.headers.cookie, undefined);
  }
});

test("rejects invalid external configuration before any request", async (t) => {
  let calls = 0;
  const {config} = await serverFor(t, (_req, res) => { calls++; res.end("{}"); });
  const bad = [null, [], {}, {...config, url: "file:///private"},
    {...config, url: "https://user:password@example.invalid"},
    {...config, url: config.url + "?token=secret"},
    {...config, url: config.url + "#secret"},
    {...config, token: ""}, {...config, token: "secret\r\nExtra: value"},
    {...config, token: "秘密"}, {...config, account: ""},
    {...config, account: "secret\naccount"}, {...config, account: 1}];
  for (const value of bad)
    await assert.rejects(getCode(value, APPID), {message: "wechat_code_configuration_invalid"});
  await assert.rejects(getCode(config, "another-app"), {message: "wechat_code_configuration_invalid"});
  assert.equal(calls, 0);
});

test("does not forward credentials to a redirect target or retry", async (t) => {
  let forwarded = 0, calls = 0;
  const target = await serverFor(t, (_req, res) => { forwarded++; res.end("{}"); });
  const {config} = await serverFor(t, (_req, res) => {
    calls++;
    res.writeHead(307, {Location: target.config.url + "/capture"});
    res.end("private redirect body");
  });
  await assert.rejects(getCode(config, APPID), {message: "wechat_code_redirect_rejected"});
  assert.equal(calls, 1);
  assert.equal(forwarded, 0);
});

for (const [status, reason] of [[401, "authentication_invalid"], [403, "authentication_invalid"],
  [409, "account_unavailable"], [404, "service_unavailable"], [502, "service_unavailable"]]) {
  test("HTTP " + status + " exposes only its stable service reason", async (t) => {
    let calls = 0;
    const {config} = await serverFor(t, (_req, res) => {
      calls++;
      res.writeHead(status);
      res.end(JSON.stringify({msg: TOKEN + ACCOUNT, data: success()}));
    });
    await assert.rejects(getCode(config, APPID), {message: "wechat_code_" + reason});
    assert.equal(calls, 1);
  });
}

test("rejects malformed or unsuccessful envelopes instead of guessing other code fields", async (t) => {
  const fixtures = ["<html>private login</html>", "null", "[]", "{}",
    JSON.stringify({...success(), code: 401}),
    JSON.stringify({code: 0, data: {code: "old-service-code"}}),
    JSON.stringify({code: 0, data: {result: {code: "opaque-code", errMsg: "login:fail"}}}),
    ...[null, 0, "", " \t", "bad\ncode", "x".repeat(513)].map((code) => JSON.stringify(success(code)))];
  let calls = 0;
  const {config} = await serverFor(t, (_req, res) => res.end(fixtures[calls++]));
  for (const fixture of fixtures)
    await assert.rejects(getCode(config, APPID), {message: "wechat_code_response_invalid"});
  assert.equal(calls, fixtures.length);
});

test("bounds the announced response size before buffering", async (t) => {
  const {config} = await serverFor(t, (_req, res) => {
    res.writeHead(200, {"Content-Length": 65_537});
    res.flushHeaders();
  });
  await assert.rejects(getCode(config, APPID), {message: "wechat_code_response_too_large"});
});

test("also bounds chunked responses without Content-Length", async (t) => {
  const {config} = await serverFor(t, (_req, res) => {
    res.write(" ");
    res.end("x".repeat(65_536));
  });
  await assert.rejects(getCode(config, APPID), {message: "wechat_code_response_too_large"});
});

test("connection interruption is sanitized and is not retried", async (t) => {
  let calls = 0;
  const {config} = await serverFor(t, (req) => { calls++; req.socket.destroy(); });
  await assert.rejects(getCode(config, APPID), {message: "wechat_code_connection_failed"});
  assert.equal(calls, 1);
});

test("deadline covers a response that keeps streaming", async (t) => {
  let started;
  const observed = new Promise((resolve) => { started = resolve; });
  let outgoing;
  const {config} = await serverFor(t, (_req, res) => {
    outgoing = res;
    res.writeHead(200);
    res.write(" ");
    started();
  });
  t.mock.timers.enable({apis: ["setTimeout"]});
  const outcome = assert.rejects(getCode(config, APPID), {message: "wechat_code_timeout"});
  await observed;
  for (let i = 0; i < 3; i++) {
    outgoing.write(" ");
    await new Promise(setImmediate);
    t.mock.timers.tick(10_000);
  }
  await outcome;
});
