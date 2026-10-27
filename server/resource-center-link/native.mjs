import fs from "node:fs";
import path from "node:path";
import { createHash } from "node:crypto";

export const fingerprint = (value) => (value ? createHash("sha256").update(value).digest("hex") : null);
export const canonical = (value, protocol) => {
  const u = new URL(value);
  if (!["http:", "https:"].includes(u.protocol)) throw new Error("需要 HTTP(S) API 地址");
  u.username = "";
  u.password = "";
  u.search = "";
  u.hash = "";
  u.pathname = u.pathname.replace(/\/+$/, "");
  if (protocol !== "Gemini") u.pathname = u.pathname.replace(/\/v1$/, "");
  return u.href.replace(/\/$/, "");
};
export const readSettings = (dirs) =>
  JSON.parse(fs.readFileSync(path.join(dirs.root, "settings.json"), "utf8"));
const apiInfo = (api) => {
  if (api === "custom") return { protocol: "OpenAI", key: "api_key_custom" };
  if (["google", "makersuite"].includes(api))
    return {
      protocol: "Gemini",
      key: "api_key_makersuite",
      url: "https://generativelanguage.googleapis.com",
    };
  if (api === "claude")
    return { protocol: "Anthropic", key: "api_key_claude", url: "https://api.anthropic.com" };
  if (api === "openai") return { protocol: "OpenAI", key: "api_key_openai", url: "https://api.openai.com" };
  throw new Error(`尚不支持的原生 API：${String(api || "未指定")}`);
};
function presetOf(profile, dirs) {
  if (!profile.preset || profile.exclude?.includes("preset")) return {};
  const root = path.resolve(dirs.openAI_Settings),
    file = path.resolve(root, `${profile.preset}.json`);
  if (!file.startsWith(root + path.sep)) throw new Error("预设路径无效");
  // A missing generation preset must not prevent syncing explicit connection fields.
  if (!fs.existsSync(file)) return {};
  return JSON.parse(fs.readFileSync(file, "utf8"));
}
export function profileFacts(profile, index, settings, dirs, manager) {
  if (profile.mode !== "cc") throw new Error("该连接不是已支持的 Chat Completion 接法");
  const preset = presetOf(profile, dirs),
    info = apiInfo(profile.api || preset.chat_completion_source);
  const proxies = settings.proxies || [],
    proxy = profile.proxy ? proxies.find((p) => p.name === profile.proxy) : null;
  if (profile.proxy && !["<None>", "<Empty>"].includes(profile.proxy) && !proxy)
    throw new Error("连接引用的代理配置不存在");
  const baseUrl = canonical(
    info.protocol === "OpenAI" && profile.api === "custom"
      ? profile["api-url"] || preset.custom_url
      : proxy?.url || info.url,
    info.protocol,
  );
  const credential =
    profile.api !== "custom" && proxy?.url
      ? proxy.password || ""
      : manager.readSecret(info.key, profile["secret-id"] || null);
  return {
    snapshot: {
      name: profile.name,
      baseUrl,
      protocol: info.protocol,
      selectedModel: String(
        profile.model || preset.custom_model || preset.google_model || preset.claude_model || "",
      ),
      order: index,
      enabled: true,
      note: "",
      credentialFingerprint: fingerprint(credential),
    },
    credential,
  };
}
export function inventory(settings, dirs, manager) {
  return (settings.extension_settings?.connectionManager?.profiles || []).map((p, index) => {
    try {
      return { nativeConnectionId: p.id, ...profileFacts(p, index, settings, dirs, manager) };
    } catch (e) {
      return { nativeConnectionId: p.id, snapshot: null, error: e.message };
    }
  });
}
export function requestFacts(body, manager, util) {
  const info = apiInfo(body.chat_completion_source);
  const baseUrl = canonical(
    body.chat_completion_source === "custom" ? body.custom_url : body.reverse_proxy || info.url,
    info.protocol,
  );
  let credential =
    body.chat_completion_source !== "custom" && body.reverse_proxy
      ? body.proxy_password || ""
      : manager.readSecret(info.key, body.secret_id || null);
  let model = String(body.model || ""),
    credentialVerified = true;
  if (body.chat_completion_source === "custom" && util) {
    const headers = { Authorization: "Bearer " + credential },
      effective = { model };
    util.mergeObjectWithYaml(headers, body.custom_include_headers);
    util.mergeObjectWithYaml(effective, body.custom_include_body);
    util.excludeKeysByYaml(effective, body.custom_exclude_body);
    const auth = Object.entries(headers).filter(([k]) => k.toLowerCase() === "authorization");
    credentialVerified = auth.length === 1 && /^Bearer\s/i.test(String(auth[0][1]));
    credential = credentialVerified ? String(auth[0][1]).replace(/^Bearer\s*/i, "") : "";
    model = String(effective.model || "");
  }
  return {
    baseUrl,
    protocol: info.protocol,
    model,
    ...(credentialVerified ? {} : { credentialVerified: false }),
    credentialFingerprint: fingerprint(credential),
  };
}
/** Build a saved Profile without selecting it or running slash commands / model discovery. */
export function nativePatch(settings, profile, remote, manager, previous) {
  const next = { ...profile, name: remote.name, model: remote.selectedModel };
  const proxies = structuredClone(settings.proxies || []);
  if (remote.protocol === "OpenAI" || remote.protocol === "OpenAI Responses") {
    if (remote.protocol === "OpenAI Responses")
      throw new Error("该酒馆版本尚未提供已验证的 Responses 保存适配");
    next.api = "custom";
    // Center canonicalizes a trailing /v1; preserve the native endpoint convention.
    const previousUrl = String(profile["api-url"] || "").replace(/\/+$/, "");
    next["api-url"] =
      /\/v1$/.test(previousUrl) && !/\/v1$/.test(remote.baseUrl)
        ? remote.baseUrl.replace(/\/+$/, "") + "/v1"
        : remote.baseUrl;
    delete next.proxy;
    if (remote.credential) {
      if (previous?.credentialFingerprint === remote.credentialFingerprint && previous.secretId)
        next["secret-id"] = previous.secretId;
      else if (
        fingerprint(manager.readSecret("api_key_custom", next["secret-id"] || null)) !==
        remote.credentialFingerprint
      ) {
        // The native API activates a new key; restore the previous global active key in the same turn.
        const all = manager._readSecretsFile();
        const active = all.api_key_custom?.find((s) => s.active)?.id;
        next["secret-id"] = manager.writeSecret(
          "api_key_custom",
          remote.credential,
          `资源中心 · ${profile.id}`,
        );
        if (active) manager.rotateSecret("api_key_custom", active);
        else {
          const secrets = manager._readSecretsFile();
          for (const item of secrets.api_key_custom || []) item.active = false;
          manager._writeSecretsFile(secrets);
        }
      }
    }
  } else if (["Gemini", "Anthropic"].includes(remote.protocol)) {
    next.api = remote.protocol === "Gemini" ? "google" : "claude";
    const name = `资源中心 · ${profile.id}`,
      old = proxies.find((p) => p.name === next.proxy),
      i = proxies.findIndex((p) => p.name === name);
    const proxy = { name, url: remote.baseUrl, password: remote.credential || old?.password || "" };
    if (i >= 0) proxies[i] = proxy;
    else proxies.push(proxy);
    next.proxy = name;
  } else throw new Error("尚不支持该协议的原生保存");
  return {
    profile: next,
    proxies,
    secretId: next["secret-id"],
    credentialFingerprint: remote.credentialFingerprint,
  };
}
