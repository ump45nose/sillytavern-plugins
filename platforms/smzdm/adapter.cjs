"use strict";
// Adapted from smzdm-checkin-ql at source-lock.json; MIT license in upstream/.
const { publish } = require("../../common/result.cjs");
const crypto = require("node:crypto");
const { journal } = require("./state.cjs");
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
async function run(request, cookie, sk, state = journal(null, "test", "test")) {
  if (!cookie || !cookieValue(cookie, "sess"))
    return outcome("failed", "missing_session", "blocked");
  if (!sk && !cookieValue(cookie, "device_id"))
    return outcome("failed", "missing_device", "blocked");
  let reason = "sign_confirmed",
    failed = false;
  if (state.get("checkin") === "unknown") {
    // Persist intent before sending: a killed process or timeout is not a retry grant.
    state.set("checkin", "pending");
    let sign;
    try {
      sign = await request("/checkin", {
        touchstone_event: "",
        sk: sk || "1",
        token: cookieValue(cookie, "sess"),
        captcha: "",
      });
    } catch {
      failed = true;
      reason = "checkin_pending_confirmation";
    }
    if (sign) {
      const msg = String(
        sign.payload?.error_msg || sign.payload?.error_message || "",
      );
      if (sign.payload?.error_code == "0" || /已签到|already/i.test(msg)) {
        state.set("checkin", "complete");
        if (sign.payload?.error_code != "0") reason = "already_complete";
      } else if (/验证码|验证|captcha/i.test(msg)) {
        return outcome("failed", "human_required", "blocked");
      } else if (/限制|风控|异常活动|restricted/i.test(msg)) {
        return outcome("failed", "restriction_detected", "blocked");
      } else {
        failed = true;
        reason = classifyError(sign);
      }
    }
  }
  // all_reward and show_view_v2 are queries in the pinned source, despite POST.
  // They may recover independently even when checkin was already confirmed.
  let reward = state.get("reward"),
    extra = state.get("extra");
  try {
    const rewards = await request("/checkin/all_reward");
    if (rewards.payload?.error_code == "0") {
      state.set("reward", "complete");
      reward = "complete";
    }
  } catch {
    failed = true;
    reason = "reward_readback_failed";
  }
  try {
    const view = await request("/checkin/show_view_v2");
    const rows = view.payload?.data?.rows;
    if (view.payload?.error_code == "0" && Array.isArray(rows)) {
      const continuous = rows.find((x) => x?.cell_type == "18001");
      const flag =
        continuous?.cell_data?.checkin_continue?.continue_checkin_reward_show;
      if (
        flag &&
        state.get("checkin") === "complete" &&
        !["pending", "complete"].includes(state.get("extra"))
      ) {
        state.set("extra", "pending");
        const claim = await request("/checkin/extra_reward");
        if (claim.payload?.error_code == "0") state.set("extra", "complete");
      } else if (
        (flag === false || flag === 0) &&
        state.get("extra") !== "pending" &&
        state.get("extra") !== "complete"
      ) {
        state.set("extra", "not_applicable");
      }
    }
  } catch {
    failed = true;
    reason = "reward_readback_failed";
  }
  extra = state.get("extra");
  const checkin = state.get("checkin") === "complete" ? "complete" : "unknown";
  // The source has no authenticated checkin readback field or extra-claim receipt.
  // A vanished offer alone must not turn an ambiguous write into completion.
  if (state.get("checkin") === "pending" || extra === "pending") {
    failed = true;
    reason = "write_pending_confirmation";
  }
  return outcome(
    failed ? "failed" : "ok",
    reason,
    checkin,
    reward,
    extra === "pending" ? "unknown" : extra,
  );
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
  if (!cookie || !cookieValue(cookie, "sess")) {
    o = outcome("failed", "missing_session", "blocked");
  } else if (!sk && !cookieValue(cookie, "device_id")) {
    o = outcome("failed", "missing_device", "blocked");
  } else {
    let state;
    try {
      state = journal(
        process.env.BENEFITS_STATE_DIR,
        process.env.BENEFITS_ACCOUNT,
        process.env.BENEFITS_BUSINESS_DATE,
        process.env.BENEFITS_LAST_CONFIRMED_PATH,
      );
    } catch {
      o = outcome("failed", "invalid_action_state");
    }
    if (state) {
      try {
        o = await run(
          transport(
            cookie,
            process.env.SMZDM_USER_AGENT_APP ||
              `smzdm_android_V${APP_VERSION} rv:${APP_REV} (Android10.0;zh)smzdmapp`,
          ),
          cookie,
          sk,
          state,
        );
      } catch {
        o = outcome(
          "failed",
          "state_or_provider_error",
          state.get("checkin") === "complete" ? "complete" : "unknown",
          state.get("reward") === "complete" ? "complete" : "unknown",
          ["complete", "not_applicable"].includes(state.get("extra"))
            ? state.get("extra")
            : "unknown",
        );
      }
    }
  }
  publish(o.execution, o.reason, o.business);
}
if (require.main === module) main();
module.exports = {
  run,
  main,
  signedForm,
  cookieValue,
  classifyError,
  transport,
};
