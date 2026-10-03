"use strict";
// Minimal OAuth binding from v4.3.2 MobileAccessLogin, GPL-3.0-or-later.
// The token and the one-shot HTTP context are owned by this invocation.
const fs = require("node:fs"), path = require("node:path"), crypto = require("node:crypto");
const common = require("./browser_common.cjs");
const CLIENT = "0000000040170455";
const REDIRECT = "https://login.live.com/oauth20_desktop.srf";
const SCOPE = "service::prod.rewardsplatform.microsoft.com::MBI_SSL";

async function create({stateDir, proxy, state, chromium, config = {}, onVerifiedState}) {
  const file = path.join(stateDir, "app-token.json");
  let token;
  try { token = common.boundedJson(file, 32768); }
  catch (e) { if (e.code !== "ENOENT") throw Error("app_token_invalid"); }
  if (token && (typeof token.access_token !== "string" || !token.access_token ||
      token.access_token.length > 16384 || !Number.isFinite(token.expires_at)))
    throw Error("app_token_invalid");
  if (!token?.access_token || token.expires_at <= Date.now() + 60000) {
    const nonce = crypto.randomBytes(16).toString("hex");
    const auth = new URL("https://login.live.com/oauth20_authorize.srf");
    for (const [k,v] of Object.entries({response_type: "code", client_id: CLIENT,
      redirect_uri: REDIRECT, scope: SCOPE, state: nonce, access_type: "offline_access"}))
      auth.searchParams.set(k,v);
    const out = await common.withBrowser(chromium || common.dependency(process.env.REWARDS_ROOT),
      state || common.readState(stateDir), {proxy, onVerifiedState}, async (context, page) => {
        await page.goto(auth.href, {waitUntil: "domcontentloaded", timeout: 45000});
        try { await page.waitForURL(u => u.origin + u.pathname === REDIRECT, {timeout: 20000}); }
        catch { await common.guard(page); throw Error("app_authorization_unavailable"); }
        const final = new URL(page.url());
        if (final.origin + final.pathname !== REDIRECT ||
            final.searchParams.get("state") !== nonce || !final.searchParams.get("code"))
          throw Error("app_authorization_unavailable");
        const response = await context.request.post("https://login.live.com/oauth20_token.srf", {
          form: {grant_type: "authorization_code", client_id: CLIENT,
            code: final.searchParams.get("code"), redirect_uri: REDIRECT, scope: SCOPE},
          timeout: 20000, maxRedirects: 0,
        });
        try {
          const bytes = await response.body();
          if (response.status() !== 200 || bytes.length > 32768) throw Error("app_token_exchange_failed");
          const raw = JSON.parse(bytes);
          if (typeof raw.access_token !== "string" || raw.access_token.length > 16384 ||
              !Number.isFinite(Number(raw.expires_in))) throw Error("app_token_exchange_failed");
          token = {access_token: raw.access_token, expires_at: Date.now() + Number(raw.expires_in) * 1000};
          return {execution: "ok"};
        } finally { await response.dispose(); }
      });
    if (out.execution !== "ok") throw Error("app_authorization_unavailable");
    const tmp = file + ".tmp";
    fs.writeFileSync(tmp, JSON.stringify(token), {mode: 0o600}); fs.renameSync(tmp,file);
  }
  const request = require(path.join(process.env.REWARDS_ROOT, "node_modules/patchright")).request;
  const http = await request.newContext({...(proxy ? {proxy: {server: proxy}} : {}), ignoreHTTPSErrors: false});
  const fetchImpl = async (url, init) => {
    const response = await http.fetch(url, {method: init.method, headers: init.headers,
      data: init.body, timeout: 20000, maxRedirects: 0});
    try {
      const bytes = await response.body();
      if (bytes.length > 1048576) throw Error("app_response_too_large");
      return new Response(bytes, {status: response.status()});
    } finally { await response.dispose(); }
  };
  return {client: require("./app.cjs").createClient({token: token.access_token,
    country: config.region || "US", language: config.language || "en-US", fetchImpl}),
    close: () => http.dispose()};
}
module.exports = {create};
