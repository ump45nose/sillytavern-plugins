"use strict";

// Independently implemented protocol adapter; exact reference is in provider-source.json.
const path = require("node:path");
const {publish} = require("../../common/result.cjs");
const {number, metric} = require("../../common/details.cjs");
const {readPrivate, binding, store} = require("./state.cjs");

const APP_ID = "wx92782ef90ebc836d";
const KDT_ID = "149536603";
const ORIGIN = "https://h5.youzan.com";
const PATHS = {
  login: "/wscshop/weapp/authorize.json",
  page: "/wscump/checkin/show_checkin_page_v2.json",
  checkin: "/wscump/checkin/checkinV2.json",
  points: "/wscump/integral/user_points.json",
};
const USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 " +
  "(KHTML, like Gecko) MicroMessenger/3.9.12 MiniProgramEnv/Windows WindowsWechat/WMPF";
const object = value => value !== null && typeof value === "object" && !Array.isArray(value);
const text = (value, limit) => typeof value === "string" && value.length > 0 &&
  value.length <= limit && !/[\x00-\x1f\x7f]/.test(value);

class MerchantError extends Error {
  constructor(reason) { super(reason); this.reason = reason; }
}

function sessionValue(value) {
  if (!object(value)) throw new MerchantError("merchant_login_response_invalid");
  const accessToken = value.accessToken ?? value.access_token;
  const sessionId = value.sessionId ?? value.session_id ?? "";
  const kdtId = String(value.kdtId ?? value.kdt_id ?? KDT_ID);
  const cookie = value.cookie ?? "";
  if (!text(accessToken, 4096) || typeof sessionId !== "string" || sessionId.length > 4096 ||
      /[\x00-\x1f\x7f]/.test(sessionId) || kdtId !== KDT_ID ||
      typeof cookie !== "string" || cookie.length > 32768 || /[\r\n]/.test(cookie))
    throw new MerchantError("merchant_login_response_invalid");
  return {accessToken, sessionId, kdtId, cookie};
}

function configValue(value) {
  if (!object(value) || !object(value.wechat) ||
      !text(value.wechat.url, 2048) || !text(value.wechat.token, 4096) ||
      !text(value.wechat.account, 128) || /\s/.test(value.wechat.account) ||
      value.user_agent !== undefined && !text(value.user_agent, 2048))
    throw new MerchantError("configuration_invalid");
  let url;
  try { url = new URL(value.wechat.url); }
  catch { throw new MerchantError("configuration_invalid"); }
  if (!["http:", "https:"].includes(url.protocol) || url.username || url.password || url.search || url.hash)
    throw new MerchantError("configuration_invalid");
  return {wechat: {...value.wechat, url: url.href.replace(/\/$/, "")}, userAgent: value.user_agent || USER_AGENT};
}

function classify(status, payload) {
  const code = object(payload) ? payload.code : null;
  const message = object(payload) && typeof payload.msg === "string" ? payload.msg : "";
  if (status === 401 || Number(code) === 401 ||
      /未登录|请先登录|登录(?:已)?(?:过期|失效)|(?:access_?token|session)[^\n]{0,40}(?:invalid|expired|无效|失效|过期)/i.test(message))
    return "merchant_authentication_invalid";
  if (status === 403) return "merchant_access_denied";
  if (status === 429) return "merchant_rate_limited";
  if (status >= 500) return "merchant_unavailable";
  if (status !== 200) return "merchant_http_error";
  if (!object(payload) || typeof code !== "number") return "merchant_response_invalid";
  if (code === 0) return null;
  // A participation limit may be lifetime/activity-wide; it is not a daily receipt.
  if (/^(?:今日|今天)(?:已经|已)签到[！!。.]?$/.test(message)) return "merchant_already_checked_in";
  return "merchant_business_rejected";
}

function mergeCookies(existing, headers) {
  const cookies = new Map(existing.split(/;\s*/).filter(Boolean).map(row => {
    const index = row.indexOf("="); return [row.slice(0, index), row.slice(index + 1)];
  }));
  for (const row of headers?.getSetCookie?.() || []) {
    const pair = row.split(";", 1)[0], index = pair.indexOf("=");
    if (index > 0) cookies.set(pair.slice(0, index), pair.slice(index + 1));
  }
  return [...cookies].map(([key, value]) => `${key}=${value}`).join("; ");
}

function transport(userAgent = USER_AGENT, fetcher = fetch) {
  return async (kind, session, data = {}) => {
    if (!Object.hasOwn(PATHS, kind)) throw new MerchantError("merchant_request_invalid");
    const target = new URL(PATHS[kind], ORIGIN);
    const headers = {
      "User-Agent": userAgent,
      "Accept": "application/json",
      "Referer": `https://servicewechat.com/${APP_ID}/17/page-frame.html`,
      "Extra-Data": JSON.stringify({sid: session?.sessionId || "", version: "2.226.7.101",
        clientType: "weapp-miniprogram", client: "weapp", bizEnv: "wsc"}),
    };
    if (session) {
      target.searchParams.set("app_id", APP_ID);
      target.searchParams.set("kdt_id", KDT_ID);
      target.searchParams.set("access_token", session.accessToken);
      if (session.cookie) headers.Cookie = session.cookie;
    }
    if (kind === "checkin") target.searchParams.set("checkinId", data.checkinId);
    if (kind === "login") headers["Content-Type"] = "application/json";
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 15000);
    try {
      const response = await fetcher(target, {
        method: kind === "login" ? "POST" : "GET", headers,
        ...(kind === "login" ? {body: JSON.stringify({appId: APP_ID, clientBiz: "weapp_wsc", code: data.code})} : {}),
        redirect: "manual", signal: controller.signal,
      });
      if (response.status >= 300 && response.status < 400) throw new MerchantError("merchant_redirect_rejected");
      const chunks = [];
      let size = 0;
      for await (const chunk of response.body || []) {
        size += chunk.length;
        if (size > 1024 * 1024) {
          controller.abort();
          throw new MerchantError("merchant_response_limit");
        }
        chunks.push(chunk);
      }
      if (response.status !== 200) throw new MerchantError(classify(response.status, {}));
      let payload;
      try { payload = JSON.parse(Buffer.concat(chunks).toString("utf8")); }
      catch { throw new MerchantError("merchant_response_invalid"); }
      const reason = classify(response.status, payload);
      if (reason) throw new MerchantError(reason);
      if (session) {
        session.cookie = mergeCookies(session.cookie, response.headers);
        sessionValue(session);
      }
      if (kind === "login" && object(payload.data))
        return {...payload.data, cookie: mergeCookies(payload.data.cookie || "", response.headers)};
      return payload.data;
    } catch (error) {
      if (error instanceof MerchantError) throw error;
      throw new MerchantError(error.name === "AbortError" ? "merchant_request_timeout" : "merchant_network_error");
    } finally {
      clearTimeout(timer);
    }
  };
}

function pointsValue(data) {
  if (!object(data)) throw new MerchantError("merchant_points_unconfirmed");
  const value = number(data.current_points ?? data.real_points);
  if (value === null || value < 0) throw new MerchantError("merchant_points_unconfirmed");
  return value;
}

function activityValue(data) {
  const id = object(data) ? String(data.checkinId ?? "") : "";
  if (!/^[1-9][0-9]{0,19}$/.test(id)) throw new MerchantError("merchant_activity_unconfirmed");
  // isShow/showPage have no verified daily-state semantics in the source.
  return id;
}

function safeReason(error) {
  return error instanceof MerchantError ? error.reason : "state_or_provider_error";
}

async function run({config, state, request, getCode, statusOnly = false, snapshot = () => {}}) {
  let session, activity, before = null, after = null;
  let checkin = state.action()?.status === "complete" ? "complete" : "unknown";
  function outcome(execution, reason) {
    return {execution, reason, business: {checkin, points: after === null ? "unknown" : "complete"},
      details: {metrics: {balance: metric("points", after ?? before, null, before, after,
        before !== null && after !== null ? after - before : null)}, items: []}};
  }
  async function balance() {
    const value = pointsValue(await request("points", session));
    state.saveSession(session);
    return value;
  }
  try {
    const cached = state.session();
    if (cached) {
      session = sessionValue(cached);
      try { before = await balance(); }
      catch (error) {
        if (!(error instanceof MerchantError) || error.reason !== "merchant_authentication_invalid") throw error;
        state.clearSession();
        session = null;
      }
    }
    if (!session) {
      let code;
      try { code = await getCode(config.wechat, APP_ID); }
      catch (error) {
        // Only fixed code-client reasons cross the credential boundary.
        const reason = [error?.reason, error?.code, error?.message].find(value =>
          typeof value === "string" && /^wechat_code_[a-z_]{1,70}$/.test(value));
        throw new MerchantError(reason || "wechat_code_unavailable");
      }
      if (!text(code, 4096)) throw new MerchantError("wechat_code_response_invalid");
      session = sessionValue(await request("login", null, {code}));
      state.saveSession(session);
      before = await balance();
    }
    activity = activityValue(await request("page", session));
    state.saveSession(session);
    const prior = state.action();
    if (prior && prior.activity !== activity) {
      checkin = "unknown";
      return outcome("ok", "checkin_activity_changed_unconfirmed");
    }
    if (statusOnly || prior) {
      after = await balance();
      return outcome("ok", checkin === "complete" ? "checkin_confirmed" :
        prior ? "checkin_pending_confirmation" : "checkin_status_unconfirmed");
    }
    state.setAction(activity, "pending");
    let signError;
    try {
      const receipt = await request("checkin", session, {checkinId: activity});
      if (!object(receipt) || !Array.isArray(receipt.list))
        throw new MerchantError("checkin_receipt_unconfirmed");
      checkin = "complete";
      state.setAction(activity, "complete");
    } catch (error) {
      if (error instanceof MerchantError && error.reason === "merchant_already_checked_in") {
        checkin = "complete";
        state.setAction(activity, "complete");
      } else if (checkin === "complete") throw error; // A storage failure cannot revoke the received receipt.
      else signError = safeReason(error);
    }
    snapshot(outcome("ok", checkin === "complete" ? "checkin_confirmed" : "checkin_pending_confirmation"));
    // These are queries, never a second checkinV2 call after an uncertain GET write.
    const currentActivity = activityValue(await request("page", session));
    after = await balance();
    if (currentActivity !== activity) return outcome("ok", "checkin_readback_activity_changed");
    return outcome("ok", signError || "checkin_confirmed");
  } catch (error) {
    return outcome("failed", safeReason(error));
  }
}

function codeClient(config, appid) {
  let client;
  try { client = require("../../common/wechat_code.cjs"); }
  catch { throw new MerchantError("wechat_code_client_unavailable"); }
  return client.getCode(config, appid);
}

async function main() {
  let output;
  try {
    const file = process.env.YINGSHIJUFENG_CONFIG;
    if (!file) throw new MerchantError("missing_configuration");
    if (!path.isAbsolute(file)) throw new MerchantError("configuration_invalid");
    const config = configValue(readPrivate(file));
    const state = store(process.env.BENEFITS_STATE_DIR,
      binding(process.env.BENEFITS_ACCOUNT, config.wechat), process.env.BENEFITS_BUSINESS_DATE);
    const emit = value => publish(value.execution, value.reason, value.business, value.details);
    output = await run({config, state, request: transport(config.userAgent), getCode: codeClient,
      statusOnly: process.argv.includes("--status"), snapshot: emit});
  } catch (error) {
    const reason = error instanceof MerchantError ? error.reason :
      ["invalid_action_state", "invalid_session_state", "private_file_invalid"].includes(error.message)
        ? error.message : "configuration_or_io_error";
    output = {execution: "failed", reason, business: {checkin: "unknown", points: "unknown"},
      details: {metrics: {}, items: []}};
  }
  publish(output.execution, output.reason, output.business, output.details);
}

if (require.main === module) main();
module.exports = {APP_ID, KDT_ID, PATHS, MerchantError, sessionValue, configValue, classify,
  transport, pointsValue, activityValue, run, main};
