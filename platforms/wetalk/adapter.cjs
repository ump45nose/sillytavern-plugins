"use strict";

// Independently implemented protocol client. See provider-source.json for the reference.
const fs = require("node:fs");
const path = require("node:path");
const crypto = require("node:crypto");
const { validateHeaderName, validateHeaderValue } = require("node:http");
const { publish } = require("../../common/result.cjs");
const { metric, number } = require("../../common/details.cjs");
const { journal } = require("./state.cjs");
const {isPrivateFile} = require("../../common/private_file.cjs");

const ORIGIN = "https://api.wetalkapp.com";
const SIGNING_SUFFIX = "0fOiukQq7jXZV2GRi9LGlO"; // Public application protocol constant, not an account secret.
const ACTIONS = new Set(["queryBalanceAndBonus", "checkIn"]);
const OMIT_HEADERS = new Set([
  "host", "content-length", "content-type", "connection", "proxy-connection",
  "keep-alive", "transfer-encoding", "upgrade", "te", "trailer", "accept-encoding",
]);
const REASONS = new Set([
  "missing_configuration", "invalid_configuration", "private_configuration_unreadable",
  "signature_parameters_unsupported", "invalid_action_state", "account_identity_mismatch",
  "action_state_io_error", "authentication_invalid", "signature_invalid", "rate_limited",
  "access_denied", "provider_unavailable", "unexpected_redirect", "response_limit",
  "invalid_provider_response", "network_error", "request_timeout", "checkin_rejected",
]);

function failure(reason) {
  return Object.assign(new Error(reason), { reason });
}
function reasonOf(error) {
  return REASONS.has(error?.reason) ? error.reason : "network_error";
}
function record(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}
function coin(value) {
  const parsed = number(value);
  return parsed !== null && parsed >= 0 ? parsed : null;
}

function configuration(value) {
  if (!record(value) || Object.keys(value).some(k => !["params", "headers"].includes(k)) ||
      !record(value.params) || !record(value.headers ?? {}) ||
      Object.keys(value.params).length > 64 || Object.keys(value.headers ?? {}).length > 64) {
    throw failure("invalid_configuration");
  }
  const params = Object.create(null);
  for (const [key, text] of Object.entries(value.params)) {
    if (key === "sign" || key === "signDate") continue;
    if (!key || key.length > 128 || /[\x00-\x1f\x7f]/.test(key) ||
        typeof text !== "string" || text.length > 4096 || /[\x00-\x1f\x7f]/.test(text)) {
      throw failure("invalid_configuration");
    }
    // The pinned source's hand-written MD5 does not UTF-8 encode JavaScript strings.
    // ASCII matches native MD5 exactly; do not invent a different Unicode wire signature.
    if (/[^\x00-\x7f]/.test(key + text)) throw failure("signature_parameters_unsupported");
    params[key] = text;
  }
  if (!params.email?.trim()) throw failure("invalid_configuration");
  const headers = Object.create(null);
  for (const [key, text] of Object.entries(value.headers ?? {})) {
    const normalized = key.toLowerCase();
    if (normalized.startsWith(":") || OMIT_HEADERS.has(normalized) ||
        normalized.startsWith("proxy-")) continue;
    if (Object.hasOwn(headers, normalized) || typeof text !== "string" || text.length > 8192) {
      throw failure("invalid_configuration");
    }
    try {
      validateHeaderName(normalized);
      validateHeaderValue(normalized, text);
    } catch {
      throw failure("invalid_configuration");
    }
    headers[normalized] = text;
  }
  headers.accept ??= "application/json";
  return { params, headers };
}

function loadConfig(filename) {
  if (!filename) throw failure("missing_configuration");
  if (!path.isAbsolute(filename)) throw failure("invalid_configuration");
  let value;
  try {
    const fd = fs.openSync(filename, fs.constants.O_RDONLY | fs.constants.O_NOFOLLOW);
    try {
      const stat = fs.fstatSync(fd);
      if (!isPrivateFile(stat)) {
        throw failure("private_configuration_unreadable");
      }
      const bytes = Buffer.alloc(16385);
      const size = fs.readSync(fd, bytes, 0, bytes.length, 0);
      if (size > 16384) throw failure("invalid_configuration");
      value = JSON.parse(bytes.subarray(0, size).toString("utf8"));
    } finally {
      fs.closeSync(fd);
    }
  } catch (error) {
    if (error.reason) throw error;
    throw failure(error instanceof SyntaxError ? "invalid_configuration" : "private_configuration_unreadable");
  }
  return configuration(value);
}

function signedParams(params, now = new Date()) {
  const data = Object.create(null);
  for (const [key, value] of Object.entries(params)) {
    if (key !== "sign" && key !== "signDate") data[key] = value;
  }
  data.signDate = now.toISOString().slice(0, 19).replace("T", " ");
  const canonical = Object.keys(data).sort().map(key => `${key}=${data[key]}`).join("&");
  if (/[^\x00-\x7f]/.test(canonical)) throw failure("signature_parameters_unsupported");
  data.sign = crypto.createHash("md5").update(canonical + SIGNING_SUFFIX, "ascii").digest("hex");
  return data;
}

function requestUrl(action, params, now = new Date()) {
  if (!ACTIONS.has(action)) throw failure("invalid_configuration");
  const data = signedParams(params, now);
  return `${ORIGIN}/app/${action}?` + Object.keys(data).sort()
    .map(key => `${encodeURIComponent(key)}=${encodeURIComponent(data[key])}`).join("&");
}

function transport(config, fetcher = globalThis.fetch, now = () => new Date()) {
  return async action => {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 30000);
    try {
      const response = await fetcher(requestUrl(action, config.params, now()), {
        method: "GET", headers: config.headers, redirect: "manual", signal: controller.signal,
      });
      // Redirects must not forward a URL containing account credentials elsewhere.
      if (response.status < 200 || response.status >= 300) {
        await response.body?.cancel();
        return { httpStatus: response.status, payload: null };
      }
      const chunks = [];
      let bytes = 0;
      for await (const chunk of response.body) {
        bytes += chunk.length;
        if (bytes > 1048576) {
          controller.abort();
          throw failure("response_limit");
        }
        chunks.push(chunk);
      }
      let payload;
      try {
        payload = JSON.parse(Buffer.concat(chunks).toString("utf8"));
      } catch {
        throw failure("invalid_provider_response");
      }
      return { httpStatus: response.status, payload };
    } catch (error) {
      if (REASONS.has(error.reason)) throw error;
      throw failure(controller.signal.aborted ? "request_timeout" : "network_error");
    } finally {
      clearTimeout(timer);
    }
  };
}

function already(message) {
  return typeof message === "string" &&
    /(?:今日|今天)?已(?:经)?签到|already[ _-]*(?:checked[ _-]*in|signed[ _-]*in)|(?:checked|signed)[ _-]*in[ _-]*(?:for[ _-]*)?today/i.test(message);
}

function rejection(response) {
  const status = response?.httpStatus;
  if (status === 401) return "authentication_invalid";
  if (status === 403) return "access_denied";
  if (status === 429) return "rate_limited";
  if (status >= 300 && status < 400) return "unexpected_redirect";
  if (!Number.isInteger(status) || status >= 500) return "provider_unavailable";
  if (status < 200 || status >= 300) return "checkin_rejected";
  const message = String(response.payload?.retmsg ?? "").slice(0, 4096);
  if (/签名.{0,12}(?:错误|无效|失败|不正确)|(?:invalid|incorrect|bad)[ _-]*(?:signature|sign\b)|signature[ _-]*(?:error|invalid|mismatch)|signDate.{0,12}(?:error|invalid|expired)/i.test(message)) {
    return "signature_invalid";
  }
  if (/未登录|登录.{0,8}(?:过期|失效)|(?:账号|帐号|邮箱|用户名|密码).{0,8}(?:错误|不存在)|认证失败|not[ _-]*logged[ _-]*in|(?:invalid|expired)[ _-]*(?:token|session|password)|(?:token|session)[ _-]*(?:expired|invalid)|authentication[ _-]*failed|login[ _-]*required/i.test(message)) {
    return "authentication_invalid";
  }
  if (!record(response.payload) || !Number.isInteger(response.payload.retcode)) {
    return "invalid_provider_response";
  }
  return "checkin_rejected";
}

function apiResult(response) {
  if (response?.httpStatus !== 200 || !record(response.payload) || response.payload.retcode !== 0) {
    throw failure(rejection(response));
  }
  if (!record(response.payload.result)) throw failure("invalid_provider_response");
  return response.payload.result;
}

function snapshot(response) {
  const result = apiResult(response);
  return {
    balance: coin(result.balance),
    allowed: typeof result.isallowcheckin === "boolean" ? result.isallowcheckin : null,
    signed: result.isallowcheckin === false && already(result.notallowcheckinreason),
  };
}

async function run(request, state, { statusOnly = false } = {}) {
  let before = null, after = null, checkin = state.status === "complete" ? "complete" : "unknown";
  let balance = "unknown";
  const output = (execution, reason) => ({
    execution, reason, business: { checkin: state.status === "complete" ? "complete" : checkin, balance },
    details: { metrics: {
      balance: metric("coins", after ?? before, null, before, after,
        before !== null && after !== null ? after - before : null),
      reward: metric("coins", state.reward),
    }, items: [] },
  });
  let first;
  try {
    first = snapshot(await request("queryBalanceAndBonus"));
    before = first.balance;
    balance = before !== null ? "complete" : "unknown";
    if (first.signed) {
      state.set("complete");
      checkin = "complete";
      return output("ok", balance === "complete" ? "already_complete" : "balance_unavailable");
    }
    if (state.status === "complete") {
      return output(first.allowed === true ? "failed" : "ok",
        first.allowed === true ? "checkin_readback_conflict" : "checkin_confirmed");
    }
    if (state.status === "pending") return output("ok", "write_pending_confirmation");
    if (first.allowed !== true) {
      checkin = first.allowed === false ? "blocked" : "unknown";
      return output("ok", first.allowed === false ? "checkin_unavailable" : "checkin_state_unavailable");
    }
    if (statusOnly) {
      checkin = "incomplete";
      return output("ok", "checkin_available");
    }
    state.set("pending");
  } catch (error) {
    return output("failed", reasonOf(error));
  }

  let receipt = false, submitFailure = null;
  try {
    const response = await request("checkIn");
    if (response.httpStatus === 200 && record(response.payload) && response.payload.retcode === 0) {
      // The endpoint's business success is a receipt even when no bonus is reported.
      state.set("complete", coin(response.payload.result?.bonus));
    } else if (response.httpStatus === 200 && record(response.payload) &&
               Number.isInteger(response.payload.retcode) && already(response.payload.retmsg)) {
      state.set("complete");
    } else {
      throw failure(rejection(response));
    }
    receipt = true;
    checkin = "complete";
  } catch (error) {
    submitFailure = reasonOf(error);
    // An explicit authentication/signature/rate rejection did not accept this write.
    // A later invocation may try after a fresh successful eligibility query.
    if (["authentication_invalid", "signature_invalid", "rate_limited", "access_denied"].includes(submitFailure)) {
      try {
        state.set("unknown");
      } catch (saveError) {
        return output("failed", reasonOf(saveError));
      }
      return output("failed", submitFailure);
    }
    if (state.status === "complete") checkin = "complete";
  }

  try {
    const last = snapshot(await request("queryBalanceAndBonus"));
    after = last.balance;
    balance = after !== null ? "complete" : "unknown";
    if (last.signed) {
      state.set("complete");
      checkin = "complete";
    }
    if (state.status === "complete") {
      checkin = "complete";
      if (last.allowed === true) return output("failed", "checkin_readback_conflict");
      return output("ok", balance === "unknown" ? "balance_unavailable" :
        (receipt ? "checkin_confirmed" : "checkin_recovered"));
    }
    return output(submitFailure ? "failed" : "ok", "write_pending_confirmation");
  } catch (error) {
    balance = "unknown";
    if (state.status === "complete") checkin = "complete";
    return output("failed", reasonOf(error));
  }
}

async function main() {
  let state, result;
  try {
    const config = loadConfig(process.env.WETALK_CONFIG);
    const identity = crypto.createHash("sha256").update(config.params.email.trim().toLowerCase()).digest("hex");
    state = journal(process.env.BENEFITS_STATE_DIR, process.env.BENEFITS_ACCOUNT,
      process.env.BENEFITS_BUSINESS_DATE, identity);
    result = await run(transport(config), state, { statusOnly: process.argv.includes("--status") });
  } catch (error) {
    result = {
      execution: "failed", reason: reasonOf(error),
      business: { checkin: state?.status === "complete" ? "complete" : "unknown", balance: "unknown" },
      details: { metrics: { balance: metric("coins"), reward: metric("coins", state?.reward) }, items: [] },
    };
  }
  publish(result.execution, result.reason, result.business, result.details);
}

if (require.main === module) main().catch(() => { process.exitCode = 1; });
module.exports = { configuration, loadConfig, signedParams, requestUrl, transport, already,
  rejection, snapshot, run, main };
