"use strict";
// Minimal OAuth binding from v4.3.2 MobileAccessLogin, GPL-3.0-or-later.
// The token and the one-shot HTTP context are owned by this invocation.
const fs = require("node:fs"), path = require("node:path"), crypto = require("node:crypto");
const common = require("./browser_common.cjs");
const trace = require("./telemetry.cjs");
const CLIENT = "0000000040170455";
const REDIRECT = "https://login.live.com/oauth20_desktop.srf";
const SCOPE = "service::prod.rewardsplatform.microsoft.com::MBI_SSL";

function callback(url, nonce) {
  try {
    const value = new URL(url);
    return typeof nonce === "string" && nonce.length > 0 &&
      !value.username && !value.password && value.origin + value.pathname === REDIRECT &&
      value.searchParams.get("state") === nonce &&
      !value.searchParams.has("error") && Boolean(value.searchParams.get("code"));
  } catch { return false; }
}

async function authorizationCode(page, auth) {
  const nonce = auth.searchParams.get("state");
  if (!nonce) throw Error("app_authorization_unavailable");
  let navigationError;
  try {
    // The OAuth callback is a navigation result. Its page/resources need not
    // finish loading before the authorization code can be exchanged.
    await page.goto(auth.href, {waitUntil: "commit", timeout: 45000});
  } catch (error) {
    trace.failure("auth.browser_redirect", error);
    navigationError = error;
  }
  if (!callback(page.url(), nonce)) {
    try {
      await page.waitForURL(url => callback(url, nonce), {
        waitUntil: "commit", timeout: 20000,
      });
    } catch (error) {
      trace.failure("auth.browser_redirect", error);
      // Reconcile a navigation timeout against the exact nonce-bound callback;
      // never replay the authorization GET or exchange an unverified code.
      if (!callback(page.url(), nonce)) {
        try { await common.guard(page); }
        catch (obstacle) {
          if (obstacle instanceof require("./obstacles.cjs").Obstacle) throw obstacle;
        }
        throw Error(navigationError?.name === "TimeoutError" || error.name === "TimeoutError"
          ? "app_authorization_timeout" : "app_authorization_navigation_failed");
      }
    }
  }
  if (!callback(page.url(), nonce)) throw Error("app_authorization_unavailable");
  trace.emit("auth.browser_redirect", {has_code: true, state_matches: true, has_error: false}, "finish");
  return new URL(page.url()).searchParams.get("code");
}

function authorizationUrl() {
  const auth = new URL("https://login.live.com/oauth20_authorize.srf");
  for (const [key, value] of Object.entries({response_type: "code", client_id: CLIENT,
    redirect_uri: REDIRECT, scope: SCOPE, state: crypto.randomBytes(16).toString("hex"),
    access_type: "offline_access"})) auth.searchParams.set(key, value);
  return auth;
}

async function httpAuthorizationCode(http, auth) {
  let response;
  try {
    // Existing login cookies can complete the server redirect without a page.
    // Any interactive response falls back to the guarded browser flow.
    response = await trace.span("auth.http_redirect", {}, () => http.get(auth.href, {timeout: 20000, maxRedirects: 10}));
    const url = new URL(response.url());
    trace.emit("auth.http_redirect", {status: response.status(), route: trace.route(url.href),
      has_code: Boolean(url.searchParams.get("code")), state_matches: url.searchParams.get("state") === auth.searchParams.get("state"),
      has_error: url.searchParams.has("error")});
    if (response.status() === 200 && callback(response.url(), auth.searchParams.get("state")))
      return new URL(response.url()).searchParams.get("code");
    return null;
  } catch (error) { trace.failure("auth.http_redirect", error); return null; }
  finally { await response?.dispose(); }
}

async function exchange(request, code) {
  let response;
  try {
    response = await trace.span("auth.exchange", {}, () => request.post("https://login.live.com/oauth20_token.srf", {
      form: {grant_type: "authorization_code", client_id: CLIENT,
        code, redirect_uri: REDIRECT, scope: SCOPE},
      timeout: 20000, maxRedirects: 0,
    }));
    const bytes = await response.body();
    if (response.status() !== 200 || bytes.length > 32768) throw Error("app_token_exchange_failed");
    const raw = JSON.parse(bytes);
    if (typeof raw.access_token !== "string" || !raw.access_token || raw.access_token.length > 16384 ||
        !Number.isFinite(Number(raw.expires_in)) || Number(raw.expires_in) <= 0)
      throw Error("app_token_exchange_failed");
    return {access_token: raw.access_token, expires_at: Date.now() + Number(raw.expires_in) * 1000};
  } catch (error) { trace.failure("auth.exchange", error); throw Error("app_token_exchange_failed"); }
  finally { await response?.dispose(); }
}

async function create({stateDir, proxy, state, chromium, config = {}, onVerifiedState}) {
  const file = path.join(stateDir, "app-token.json");
  let token;
  try { token = common.boundedJson(file, 32768); }
  catch (e) { if (e.code !== "ENOENT") throw Error("app_token_invalid"); }
  if (token && (typeof token.access_token !== "string" || !token.access_token ||
      token.access_token.length > 16384 || !Number.isFinite(token.expires_at)))
    throw Error("app_token_invalid");
  const request = require(path.join(process.env.REWARDS_ROOT, "node_modules/patchright")).request;
  let http;
  try {
    const expired = !token?.access_token || token.expires_at <= Date.now() + 60000;
    trace.emit("auth.cache", {refresh_required: expired, ttl_ms: token ? Math.round(token.expires_at-Date.now()) : 0});
    const loginState = expired ? state || common.readState(stateDir) : undefined;
    http = await request.newContext({...(proxy ? {proxy: {server: proxy}} : {}),
      ...(loginState ? {storageState: loginState} : {}), ignoreHTTPSErrors: false});
    trace.instrumentRequest(http);
    if (expired) {
      const code = await httpAuthorizationCode(http, authorizationUrl());
      if (code) { trace.emit("auth.cache", {state: "http"}); token = await exchange(http, code); }
      else {
        trace.emit("auth.cache", {state: "browser"});
        const out = await common.withBrowser(chromium || common.dependency(process.env.REWARDS_ROOT),
          loginState, {proxy, onVerifiedState}, async (context, page) => {
            token = await exchange(context.request, await authorizationCode(page, authorizationUrl()));
            return {execution: "ok"};
          });
        if (out.execution !== "ok") throw Error("app_authorization_unavailable");
      }
      const tmp = file + ".tmp";
      fs.writeFileSync(tmp, JSON.stringify(token), {mode: 0o600}); fs.renameSync(tmp,file);
    }
    const fetchImpl = async (url, init) => {
      const response = await http.fetch(url, {method: init.method, headers: init.headers,
        data: init.body, timeout: 20000, maxRedirects: 0});
      try {
        const bytes = await response.body();
        if (bytes.length > 1048576) throw Error("app_response_too_large");
        return new Response(bytes, {status: response.status()});
      } finally { await response.dispose(); }
    };
    return {expiresAt: token.expires_at, client: require("./app.cjs").createClient({token: token.access_token,
      country: config.region || "US", language: config.language || "en-US", fetchImpl}),
      close: () => http.dispose()};
  } catch (error) { trace.failure("auth.cache", error); await http?.dispose(); throw error; }
}
module.exports = {create, authorizationCode, httpAuthorizationCode, exchange};
