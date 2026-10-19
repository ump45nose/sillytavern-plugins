"use strict";

// Independently implemented from the pinned public protocol in provider-source.json.
const crypto = require("node:crypto");
const path = require("node:path");
const {publish} = require("../../common/result.cjs");
const {number, metric} = require("../../common/details.cjs");
const {OleError, State, text, readPrivateJson, configurationIdentity} = require("./state.cjs");

const APP_ID = "wx6c61aaeba1551439";
const BASE_URL = "https://ole-app.crvole.com.cn";
const ENDPOINTS = {
  login: "/vgdt_app_api/v1/vgdt-fea-app-member/front_api/wechat_auths/code/mini_program",
  shop: "/vgdt_app_api/v1/vgdt-fea-app-entershop/front_api/enter_shops/shop",
  sign: "/vgdt_app_api/v1/vgdt-fea-app-member/front_api/member_sign",
};
const USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 " +
  "(KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36 MicroMessenger/7.0.20.1781(0x6700143B) " +
  "NetType/WIFI MiniProgramEnv/Windows WindowsWechat/WMPF";
const RESPONSE_LIMIT = 1024 * 1024;

function readConfig(file) {
  if (!file) throw new OleError("missing_configuration");
  if (!path.isAbsolute(file)) throw new OleError("invalid_configuration");
  let config;
  try { config = readPrivateJson(file); }
  catch { throw new OleError("invalid_private_configuration"); }
  if (!config.wechat || !text(config.wechat.url, 2048) ||
      !text(config.wechat.token) || !text(config.wechat.account, 512) ||
      (config.user_agent !== undefined && !text(config.user_agent, 2048)) ||
      (config.shop_code !== undefined && !text(config.shop_code, 128)))
    throw new OleError("invalid_configuration");
  let server;
  try { server = new URL(config.wechat.url); }
  catch { throw new OleError("invalid_configuration"); }
  if (!["https:", "http:"].includes(server.protocol) || server.username || server.password ||
      server.search || server.hash) throw new OleError("invalid_configuration");
  config.wechat.url = server.href.replace(/\/+$/, "");
  if (config.location !== undefined) {
    if (!text(config.location, 100)) throw new OleError("invalid_configuration");
    const parts = config.location.split(",");
    const longitude = number(parts[0]), latitude = number(parts[1]);
    if (parts.length !== 2 || longitude === null || latitude === null ||
        Math.abs(longitude) > 180 || Math.abs(latitude) > 90)
      throw new OleError("invalid_configuration");
    config.location = `${longitude},${latitude}`;
  }
  return config;
}

function identifier(value) {
  const string = typeof value === "number" && Number.isSafeInteger(value) ? String(value) : value;
  return text(string, 128) ? string : null;
}

function dataOf(response) {
  const status = response?.httpStatus, payload = response?.payload;
  if ([401, 403].includes(status) || [401, 403].includes(Number(payload?.state_code)))
    throw new OleError("authentication_invalid");
  if (status === 429) throw new OleError("rate_limited");
  if (status !== 200) throw new OleError("merchant_http_error");
  if (!payload || Number(payload.state_code) !== 200)
    throw new OleError("merchant_business_rejected");
  if (!payload.data || typeof payload.data !== "object" || Array.isArray(payload.data))
    throw new OleError("merchant_response_invalid");
  return payload.data;
}

function statusOf(response) {
  const data = dataOf(response);
  if (!["Y", "N"].includes(data.sign_of_day))
    throw new OleError("checkin_status_unconfirmed");
  const points = number(data.total_integral);
  return {signed: data.sign_of_day === "Y", points: points !== null && points >= 0 ? points : null,
    shop_code: identifier(data.shop_code)};
}

function transport(config, fetcher = fetch) {
  const hash = crypto.createHash("md5").update("ole-weapp-" + config.wechat.account).digest("hex");
  const unique = `weapp-${hash.slice(0, 8)}-${hash.slice(8, 12)}-${hash.slice(12, 16)}-` +
    `${hash.slice(16, 20)}-${hash.slice(20)}`;
  return async (method, endpoint, body, session) => {
    if (!Object.values(ENDPOINTS).includes(endpoint) ||
        !["GET", "POST"].includes(method)) throw new OleError("invalid_merchant_request");
    const headers = {
      appVersion: "1.10.32", channel: "wxmini", os: "android", Tenant: "VGDT",
      "Tenant-Channel": "OLE", "Content-Type": "application/json", unique,
      "Device-Name": "WeChat MiniProgram", traceId: String(Date.now() * 1000 + crypto.randomInt(1000)),
      "User-Agent": config.user_agent || USER_AGENT,
      Referer: `https://servicewechat.com/${APP_ID}/100/page-frame.html`,
    };
    if (session) {
      headers.sessionId = session.session_id;
      headers.oleWxOpenId = session.openid;
    }
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 20000);
    try {
      const response = await fetcher(BASE_URL + endpoint, {
        method, headers, redirect: "manual", signal: controller.signal,
        ...(method === "POST" ? {body: JSON.stringify(body || {})} : {}),
      });
      if (response.status >= 300 && response.status < 400)
        throw new OleError("merchant_redirect_rejected");
      let size = 0;
      const chunks = [];
      if (!response.body) throw new OleError("merchant_response_invalid");
      for await (const chunk of response.body) {
        size += chunk.length;
        if (size > RESPONSE_LIMIT) {
          controller.abort();
          throw new OleError("merchant_response_limit");
        }
        chunks.push(Buffer.from(chunk));
      }
      let payload;
      try { payload = JSON.parse(Buffer.concat(chunks).toString("utf8")); }
      catch { throw new OleError("merchant_response_invalid"); }
      return {httpStatus: response.status, payload};
    } catch (error) {
      if (error instanceof OleError) throw error;
      throw new OleError(controller.signal.aborted ? "merchant_timeout" : "merchant_network_error");
    } finally { clearTimeout(timer); }
  };
}

function outcome(execution, reason, checkin, balance, before = null, after = null) {
  return {
    execution, reason, business: {checkin, balance},
    details: {metrics: {balance: metric("points", after ?? before, null, before, after,
      before !== null && after !== null ? after - before : null)}, items: []},
  };
}

async function execute({config, state, request, getCode}) {
  let session = state.session, refreshed = false, before = null;
  const knownComplete = () => state.checkin === "complete" ? "complete" : "unknown";
  async function login() {
    let code;
    try { code = await getCode(config.wechat, APP_ID); }
    catch (error) {
      // Only a fixed shared-client reason can cross the credential boundary.
      const safe = new Set(["wechat_code_service_unavailable", "wechat_code_authentication_invalid",
        "wechat_code_response_invalid", "wechat_code_timeout", "wechat_code_configuration_invalid",
        "wechat_code_connection_failed", "wechat_code_account_unavailable",
        "wechat_code_redirect_rejected", "wechat_code_response_too_large"]);
      throw new OleError(safe.has(error?.message) ? error.message : "wechat_code_unavailable");
    }
    if (!text(code, 2048)) throw new OleError("wechat_code_response_invalid");
    const data = dataOf(await request("POST", ENDPOINTS.login, {code}, null));
    if (!text(data.user_session) || !text(data.open_id, 512)) {
      if (data.member_id === null || data.inquire === "N")
        throw new OleError("membership_registration_required");
      throw new OleError("merchant_login_response_invalid");
    }
    session = {session_id: data.user_session, openid: data.open_id,
      shop_code: identifier(data.shop_code)};
    state.saveSession(session);
    refreshed = true;
  }
  async function query() {
    try { return statusOf(await request("GET", ENDPOINTS.sign, null, session)); }
    catch (error) {
      if (error.code !== "authentication_invalid" || refreshed) throw error;
      state.invalidateSession();
      await login();
      return statusOf(await request("GET", ENDPOINTS.sign, null, session));
    }
  }
  try {
    if (!session) await login();
    const initial = await query();
    before = initial.points;
    if (initial.signed) {
      state.record("complete");
      return outcome("ok", initial.points === null ? "checkin_confirmed_balance_unavailable" :
        "already_complete", "complete", initial.points === null ? "unknown" : "complete",
      null, initial.points);
    }
    if (["pending", "complete"].includes(state.checkin))
      return outcome("ok", state.checkin === "pending" ? "write_pending_confirmation" :
        "checkin_state_conflict", "unknown", before === null ? "unknown" : "complete", null, before);

    let shop = config.shop_code || initial.shop_code || session.shop_code;
    if (!shop && config.location) {
      const data = dataOf(await request("POST", ENDPOINTS.shop, {
        location: config.location, address_longitude: "", location_name: "", province: "",
        city: "", district: "", address: "", house_number: "", receive_mobile: "",
        receive_name: "", region_name: "", region_id: "", select: false,
      }, session));
      shop = identifier(data.shop_code);
      if (!shop) throw new OleError("shop_lookup_unconfirmed");
    }
    if (!shop) return outcome("ok", "missing_shop_configuration", "blocked",
      before === null ? "unknown" : "complete", null, before);

    state.record("pending");
    let submissionError = null;
    try { dataOf(await request("POST", ENDPOINTS.sign, {enter_shop_code: shop}, session)); }
    catch (error) { submissionError = error instanceof OleError ? error.code : "merchant_network_error"; }
    // The POST reply never completes this action. One authenticated readback does.
    const final = await query();
    if (final.signed) {
      state.record("complete");
      return outcome("ok", final.points === null ? "checkin_confirmed_balance_unavailable" :
        "checkin_confirmed", "complete", final.points === null ? "unknown" : "complete", before, final.points);
    }
    return outcome(submissionError ? "failed" : "ok", submissionError || "write_pending_confirmation",
      "unknown", final.points === null ? "unknown" : "complete", before, final.points);
  } catch (error) {
    const reason = error instanceof OleError ? error.code : "merchant_network_error";
    const checkin = reason === "membership_registration_required" ? "blocked" : knownComplete();
    return outcome("failed", reason, checkin, "unknown", before, null);
  }
}

async function main() {
  let result;
  try {
    const config = readConfig(process.env.OLE_CONFIG);
    const state = new State(process.env.BENEFITS_STATE_DIR, process.env.BENEFITS_ACCOUNT,
      process.env.BENEFITS_BUSINESS_DATE, configurationIdentity(config.wechat));
    const getCode = async (...args) => {
      let shared;
      try { shared = require("../../common/wechat_code.cjs"); }
      catch (error) {
        if (error.code === "MODULE_NOT_FOUND") throw new OleError("wechat_code_unavailable");
        throw error;
      }
      return shared.getCode(...args);
    };
    result = await execute({config, state, request: transport(config), getCode});
  } catch (error) {
    result = outcome("failed", error instanceof OleError ? error.code : "configuration_or_io_error",
      "blocked", "unknown");
  }
  publish(result.execution, result.reason, result.business, result.details);
  return result;
}

if (require.main === module) main();
module.exports = {APP_ID, BASE_URL, ENDPOINTS, RESPONSE_LIMIT, readConfig, dataOf, statusOf,
  transport, execute, main};
