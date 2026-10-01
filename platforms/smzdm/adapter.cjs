"use strict";
// Adapted from smzdm-checkin-ql at source-lock.json; MIT license in upstream/.
const { publish } = require("../../common/result.cjs");
const crypto = require("node:crypto");
const APP_VERSION = "10.4.26",
  APP_REV = "866",
  SIGN_KEY = "apr1$AwP!wRRT$gJ/q.X24poeBInlUJC";
function cookieValue(cookie, name) {
  return cookie.match(new RegExp(`(?:^|;\\s*)${name}=([^;]+)`))?.[1] || "";
}
function signedForm(data = {}, now = Date.now()) {
  const body = {
    weixin: 1,
    basic_v: 0,
    f: "android",
    v: APP_VERSION,
    time: `${Math.round(now / 1000)}000`,
    ...data,
  };
  const raw = Object.keys(body)
    .filter((k) => body[k] !== "")
    .sort()
    .map((k) => `${k}=${String(body[k]).replace(/\s+/, "")}`)
    .join("&");
  body.sign = crypto
    .createHash("md5")
    .update(`${raw}&key=${SIGN_KEY}`)
    .digest("hex")
    .toUpperCase();
  return new URLSearchParams(body).toString();
}
function classifyError(r) {
  return [401, 403].includes(r.httpStatus)
    ? "authentication_invalid"
    : r.httpStatus === 429
      ? "rate_limited"
      : !r.httpStatus || r.httpStatus >= 500
        ? "network_error"
        : "business_failure";
}
function outcome(
  execution,
  reason,
  checkin = "unknown",
  reward = "unknown",
  extra = "unknown",
) {
  return {
    execution,
    reason,
    business: { checkin, reward, extra_reward: extra },
  };
}
async function run(request, cookie, sk) {
  if (!cookie || !cookieValue(cookie, "sess"))
    return outcome("failed", "missing_session", "blocked");
  if (!sk && !cookieValue(cookie, "device_id"))
    return outcome("failed", "missing_device", "blocked");
  const sign = await request("/checkin", {
    touchstone_event: "",
    sk: sk || "1",
    token: cookieValue(cookie, "sess"),
    captcha: "",
  });
  if (sign.payload?.error_code != "0") {
    const msg = String(
      sign.payload?.error_msg || sign.payload?.error_message || "",
    );
    if (/已签到|already/i.test(msg))
      return outcome("ok", "already_complete", "complete");
    if (/验证码|验证|captcha/i.test(msg))
      return outcome("failed", "human_required", "blocked");
    if (/限制|风控|异常活动|restricted/i.test(msg))
      return outcome("failed", "restriction_detected", "blocked");
    return outcome("failed", classifyError(sign));
  }
  // Preserve confirmed sign-in if a later read/claim fails; never replay writes.
  let reward = "unknown",
    extra = "unknown";
  try {
    const rewards = await request("/checkin/all_reward");
    reward = rewards.payload?.error_code == "0" ? "complete" : "unknown";
    const view = await request("/checkin/show_view_v2");
    const rows = view.payload?.data?.rows;
    if (view.payload?.error_code == "0" && Array.isArray(rows)) {
      const continuous = rows.find((x) => x?.cell_type == "18001");
      const flag =
        continuous?.cell_data?.checkin_continue?.continue_checkin_reward_show;
      if (flag) {
        const claim = await request("/checkin/extra_reward");
        extra = claim.payload?.error_code == "0" ? "complete" : "unknown";
      } else if (flag === false || flag === 0) extra = "not_applicable";
    }
  } catch {
    return outcome(
      "failed",
      "reward_readback_failed",
      "complete",
      reward,
      extra,
    );
  }
  return outcome("ok", "sign_confirmed", "complete", reward, extra);
}
function transport(cookie, ua, fetcher = fetch) {
  return async (path, data = {}) => {
    const controller = new AbortController(),
      timer = setTimeout(() => controller.abort(), 30000);
    try {
      const r = await fetcher(`https://user-api.smzdm.com${path}`, {
        method: "POST",
        headers: {
          Accept: "*/*",
          "Accept-Language": "zh-Hans-CN;q=1",
          "Content-Type": "application/x-www-form-urlencoded",
          request_key: Array.from(crypto.randomBytes(18), (b) =>
            String(b % 10),
          ).join(""),
          "User-Agent": ua,
          Cookie: cookie,
        },
        body: signedForm(data),
        signal: controller.signal,
      });
      // Fixed response limit; avoid unbounded response.text().
      let bytes = 0,
        chunks = [];
      for await (const chunk of r.body) {
        bytes += chunk.length;
        if (bytes > 1048576) {
          controller.abort();
          throw Error("response_limit");
        }
        chunks.push(chunk);
      }
      let payload;
      try {
        payload = JSON.parse(Buffer.concat(chunks).toString());
      } catch {
        payload = {};
      }
      return { httpStatus: r.status, payload };
    } finally {
      clearTimeout(timer);
    }
  };
}
async function main() {
  const cookie = (process.env.SMZDM_COOKIE || "").trim(),
    sk = (process.env.SMZDM_SK || "").trim();
  let o;
  try {
    o = await run(
      transport(
        cookie,
        process.env.SMZDM_USER_AGENT_APP ||
          `smzdm_android_V${APP_VERSION} rv:${APP_REV} (Android10.0;zh)smzdmapp`,
      ),
      cookie,
      sk,
    );
  } catch {
    o = outcome("failed", "network_error");
  }
  publish(o.execution, o.reason, o.business);
}
if (require.main === module) main();
module.exports = { run, signedForm, cookieValue, classifyError, transport };
