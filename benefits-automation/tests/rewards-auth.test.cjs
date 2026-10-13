"use strict";
const test = require("node:test"), assert = require("node:assert/strict");
const auth = require("../platforms/rewards/app_auth.cjs");
const common = require("../platforms/rewards/browser_common.cjs");
const { Obstacle } = require("../platforms/rewards/obstacles.cjs");
const url = new URL("https://login.live.com/oauth20_authorize.srf?state=fixture-nonce");
const redirect = "https://login.live.com/oauth20_desktop.srf?state=fixture-nonce&code=fixture-code";
const timeout = () => Object.assign(Error("private OAuth URL and code"), {name: "TimeoutError"});

test("OAuth reads the nonce-bound callback at commit without waiting for its DOM", async () => {
  let current = "about:blank", navigations = 0, waits = 0;
  const page = {
    url: () => current,
    goto: async (value, options) => {
      navigations++;
      assert.equal(value, url.href);
      assert.equal(options.waitUntil, "commit");
      current = "https://login.live.com/oauth20_authorize.srf";
    },
    waitForURL: async (predicate, options) => {
      waits++;
      assert.equal(options.waitUntil, "commit");
      assert.equal(predicate(new URL(redirect)), true);
      assert.equal(predicate(new URL(redirect.replace("fixture-nonce", "wrong-nonce"))), false);
      current = redirect;
    },
  };
  assert.equal(await auth.authorizationCode(page, url), "fixture-code");
  assert.equal(navigations, 1);
  assert.equal(waits, 1);
});

test("OAuth reconciles a goto timeout when the verified callback already arrived", async () => {
  let navigations = 0;
  const page = {
    url: () => redirect,
    goto: async () => { navigations++; throw timeout(); },
    waitForURL: async () => assert.fail("callback already observed"),
  };
  assert.equal(await auth.authorizationCode(page, url), "fixture-code");
  assert.equal(navigations, 1);
});

test("OAuth reconciles a callback arriving as waitForURL times out without replay", async () => {
  let current = "about:blank", navigations = 0;
  const page = {
    url: () => current,
    goto: async () => { navigations++; throw timeout(); },
    waitForURL: async () => { current = redirect; throw timeout(); },
  };
  assert.equal(await auth.authorizationCode(page, url), "fixture-code");
  assert.equal(navigations, 1);
});

test("OAuth rejects missing state, wrong state, deceptive hosts and error callbacks", async () => {
  const savedGuard = common.guard;
  common.guard = async () => {};
  try {
    for (const current of [
      redirect.replace("fixture-nonce", "wrong-nonce"),
      redirect.replace("login.live.com", "login.live.com.evil.invalid"),
      redirect + "&error=access_denied",
      redirect.replace("state=fixture-nonce&", ""),
      redirect.replace("https://", "https://someone@"),
    ]) {
      let navigations = 0;
      const page = {url: () => current,
        goto: async () => { navigations++; throw timeout(); },
        waitForURL: async () => { throw timeout(); }};
      await assert.rejects(auth.authorizationCode(page, url), {
        message: "app_authorization_timeout",
      });
      assert.equal(navigations, 1);
    }
    await assert.rejects(auth.authorizationCode({}, new URL("https://login.live.com/")), {
      message: "app_authorization_unavailable",
    });
  } finally { common.guard = savedGuard; }
});

test("OAuth retains a real verification obstacle and redacts transport failures", async () => {
  const savedGuard = common.guard;
  const page = {url: () => "https://login.live.com/",
    goto: async () => { throw Error("private transport data"); },
    waitForURL: async () => { throw Error("private callback data"); }};
  try {
    const obstacle = new Obstacle({url: page.url(), flags: {captcha: true}});
    common.guard = async () => { throw obstacle; };
    await assert.rejects(auth.authorizationCode(page, url), e => e === obstacle);
    common.guard = async () => { throw Error("private navigation context"); };
    await assert.rejects(auth.authorizationCode(page, url), {
      message: "app_authorization_navigation_failed",
    });
  } finally { common.guard = savedGuard; }
});

test("HTTP OAuth accepts only a successful nonce-bound callback and disposes responses", async () => {
  for (const [status, target, expected] of [
    [200, redirect, "fixture-code"],
    [200, redirect.replace("fixture-nonce", "wrong-nonce"), null],
    [200, "https://login.live.com/login.srf", null],
    [200, redirect + "&error=access_denied", null],
    [403, redirect, null],
  ]) {
    let reads = 0, disposals = 0;
    const http = {get: async (value, options) => {
      reads++;
      assert.equal(value, url.href);
      assert.equal(options.maxRedirects, 10);
      return {status: () => status, url: () => target, dispose: async () => { disposals++; }};
    }};
    assert.equal(await auth.httpAuthorizationCode(http, url), expected);
    assert.equal(reads, 1);
    assert.equal(disposals, 1);
  }
  assert.equal(await auth.httpAuthorizationCode({get: async () => { throw timeout(); }}, url), null);
});

test("token exchange errors remain private and are never replayed", async () => {
  let posts = 0, disposals = 0;
  const request = {post: async (value, options) => {
    posts++;
    assert.equal(value, "https://login.live.com/oauth20_token.srf");
    assert.equal(options.maxRedirects, 0);
    assert.equal(options.form.code, "fixture-code");
    return {status: () => 200, body: async () => Buffer.from("private invalid response"),
      dispose: async () => { disposals++; }};
  }};
  await assert.rejects(auth.exchange(request, "fixture-code"), {message: "app_token_exchange_failed"});
  assert.equal(posts, 1);
  assert.equal(disposals, 1);
});

test("expired APP token refreshes through existing cookies without starting Chromium", async () => {
  const fs = require("node:fs"), os = require("node:os"), path = require("node:path");
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "rewards-auth-http-"));
  const savedRoot = process.env.REWARDS_ROOT, savedBrowser = common.withBrowser;
  let reads = 0, posts = 0, closes = 0;
  const state = {cookies: [{name: "fixture", value: "fixture", domain: "login.live.com"}], origins: []};
  const http = {
    get: async value => {
      reads++;
      const nonce = new URL(value).searchParams.get("state");
      return {status: () => 200, url: () => redirect.replace("fixture-nonce", nonce), dispose: async () => {}};
    },
    post: async () => { posts++; return {status: () => 200,
      body: async () => Buffer.from(JSON.stringify({access_token: "fresh-fixture-token", expires_in: 3600})),
      dispose: async () => {}}; },
    fetch: async (_url, options) => {
      assert.equal(options.headers.Authorization, "Bearer fresh-fixture-token");
      return {status: () => 200, body: async () => Buffer.from(JSON.stringify({response: {balance: 123}})),
        dispose: async () => {}};
    },
    dispose: async () => { closes++; },
  };
  try {
    process.env.REWARDS_ROOT = dir;
    fs.mkdirSync(path.join(dir, "node_modules/patchright"), {recursive: true});
    fs.writeFileSync(path.join(dir, "node_modules/patchright/index.js"),
      "exports.request={newContext:options=>globalThis.fixtureAuthContext(options)};");
    globalThis.fixtureAuthContext = async options => {
      assert.deepEqual(options.storageState, state);
      assert.equal(options.ignoreHTTPSErrors, false);
      assert.equal(options.proxy.server, "http://fixture.invalid:7890");
      return http;
    };
    fs.writeFileSync(path.join(dir, "app-token.json"), JSON.stringify({access_token: "expired-fixture", expires_at: 1}));
    common.withBrowser = async () => assert.fail("HTTP callback already authorized");
    const session = await auth.create({stateDir: dir, state, proxy: "http://fixture.invalid:7890"});
    assert.equal((await session.client.read()).response.balance, 123);
    const saved = JSON.parse(fs.readFileSync(path.join(dir, "app-token.json")));
    assert.equal(saved.access_token, "fresh-fixture-token");
    assert.ok(saved.expires_at > Date.now());
    assert.equal(reads, 1);
    assert.equal(posts, 1);
    await session.close();
    assert.equal(closes, 1);
  } finally {
    common.withBrowser = savedBrowser;
    delete globalThis.fixtureAuthContext;
    if (savedRoot === undefined) delete process.env.REWARDS_ROOT;
    else process.env.REWARDS_ROOT = savedRoot;
    fs.rmSync(dir, {recursive: true, force: true});
  }
});
