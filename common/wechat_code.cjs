"use strict";

// YYB-Go-Enhanced v0.2.33 protocol; provenance and integration: docs/YYB_LOGIN.md.
// No credential discovery, code cache, redirects, or automatic retry.
const http = require("node:http");
const https = require("node:https");

const TIMEOUT_MS = 30_000;
const MAX_RESPONSE_BYTES = 65_536;

function requestConfig(config, appid) {
  const invalid = () => { throw Error("wechat_code_configuration_invalid"); };
  if (!config || typeof config !== "object" || Array.isArray(config) ||
      typeof config.url !== "string" || config.url.length > 2048 ||
      config.url !== config.url.trim() ||
      typeof config.token !== "string" || !/^[\x21-\x7e]{1,4096}$/.test(config.token) ||
      typeof config.account !== "string" || !/^[^\s\x00-\x1f\x7f]{1,128}$/.test(config.account) ||
      typeof appid !== "string" || !/^wx[0-9a-f]{16}$/.test(appid)) invalid();
  let base;
  try { base = new URL(config.url); } catch { invalid(); }
  if (!["http:", "https:"].includes(base.protocol) || !base.hostname ||
      base.username || base.password || base.search || base.hash) invalid();
  base.pathname = base.pathname.replace(/\/+$/, "") + "/wxapp/getCode";
  return {url: base, token: config.token,
    body: Buffer.from(JSON.stringify({ref: config.account, app_id: appid}))};
}

/** Return one fresh wx.login code. Errors expose only a stable message. */
async function getCode(config, appid) {
  const {url, token, body} = requestConfig(config, appid);
  return new Promise((resolve, reject) => {
    let request, response, settled = false;
    const finish = (reason, code) => {
      if (settled) return;
      settled = true;
      clearTimeout(deadline);
      if (reason) {
        response?.destroy();
        request?.destroy();
        reject(Error(reason));
      } else resolve(code);
    };
    // Total deadline includes DNS, connection, TLS, headers and streamed body.
    const deadline = setTimeout(() => finish("wechat_code_timeout"), TIMEOUT_MS);
    try {
      const transport = url.protocol === "https:" ? https : http;
      request = transport.request(url, {
        method: "POST", agent: false, rejectUnauthorized: true,
        headers: {"Content-Type": "application/json", "Accept": "application/json",
          "Authorization": "Bearer " + token, "Content-Length": body.length},
      }, (incoming) => {
        response = incoming;
        incoming.on("error", () => finish("wechat_code_connection_failed"));
        incoming.on("aborted", () => finish("wechat_code_connection_failed"));
        const status = incoming.statusCode;
        if (status >= 300 && status < 400) return finish("wechat_code_redirect_rejected");
        if (status === 401 || status === 403) return finish("wechat_code_authentication_invalid");
        if (status === 409) return finish("wechat_code_account_unavailable");
        if (status !== 200) return finish("wechat_code_service_unavailable");
        if (Number(incoming.headers["content-length"]) > MAX_RESPONSE_BYTES)
          return finish("wechat_code_response_too_large");
        const chunks = [];
        let size = 0;
        incoming.on("data", (chunk) => {
          if (settled) return;
          size += chunk.length;
          if (size > MAX_RESPONSE_BYTES) return finish("wechat_code_response_too_large");
          chunks.push(chunk);
        });
        incoming.on("end", () => {
          if (settled) return;
          let payload;
          try { payload = JSON.parse(Buffer.concat(chunks, size).toString("utf8")); }
          catch { return finish("wechat_code_response_invalid"); }
          const result = payload?.data?.result;
          if (payload?.code !== 0 || result?.errMsg !== "login:ok" ||
              typeof result.code !== "string" ||
              !/^[^\s\x00-\x1f\x7f]{1,512}$/.test(result.code))
            return finish("wechat_code_response_invalid");
          finish(null, result.code);
        });
      });
      request.on("error", () => finish("wechat_code_connection_failed"));
      request.end(body);
    } catch {
      finish("wechat_code_connection_failed");
    }
  });
}

module.exports = {getCode};
