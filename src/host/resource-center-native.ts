import type { Data } from "./types";
import type { RpConnection } from "./resource-center";
const load = (path: string): Promise<any> => import(/* @vite-ignore */ path);
export async function applyNativeConnection(
  current: Data,
  remote: RpConnection,
  context: any,
  openai: any,
) {
  const patch: Data = {
    ...current,
    name: remote.name,
    model: remote.models[0],
  };
  if (remote.protocol === "OpenAI") {
    patch.api = "custom";
    patch["api-url"] = remote.baseUrl;
    if (remote.key) {
      const secrets = await load("/scripts/secrets.js"),
        key = secrets.SECRET_KEYS.CUSTOM;
      const native = async (path: string, body?: Data) => {
        const r = await fetch("/api/secrets/" + path, {
          method: "POST",
          headers: context.getRequestHeaders(),
          ...(body ? { body: JSON.stringify(body) } : {}),
        });
        if (!r.ok) throw new Error("原生凭据 " + path + " 保存失败");
        return path === "rotate" ? null : r.json();
      };
      const before = await native("read"),
        active = before[key]?.find((x: Data) => x.active)?.id;
      // Use the native endpoint without SECRET_WRITTEN/reconnect events or model discovery.
      const { id } = await native("write", {
        key,
        value: remote.key,
        label: `资源中心 ${current.id}`,
      });
      if (!id) throw new Error("原生凭据未确认保存");
      if (active) await native("rotate", { key, id: active });
      await secrets.readSecretState();
      patch["secret-id"] = id;
    }
  } else if (["Anthropic", "Gemini"].includes(remote.protocol)) {
    patch.api = remote.protocol === "Anthropic" ? "claude" : "makersuite";
    const name = `资源中心 ${current.id}`,
      previous = openai.proxies.find((p: Data) => p.name === current.proxy);
    let proxy = openai.proxies.find((p: Data) => p.name === name);
    if (!proxy) {
      proxy = {
        name,
        url: remote.baseUrl,
        password: remote.key || previous?.password || "",
      };
      openai.proxies.push(proxy);
    } else {
      proxy.url = remote.baseUrl;
      if (remote.key) proxy.password = remote.key;
    }
    patch.proxy = name;
    const select = document.querySelector<HTMLSelectElement>(
      "#openai_proxy_preset",
    );
    if (select && ![...select.options].some((o) => o.value === name)) {
      const option = document.createElement("option");
      option.value = name;
      option.textContent = name;
      select.append(option);
    }
  } else throw new Error("该原生协议尚不支持保存，请在酒馆手动维护");
  return patch;
}
export async function activateSavedConnection(
  profile: Data,
  context: any,
  openai: any,
) {
  const script = await load("/script.js");
  if (context.mainApi !== "openai") {
    script.changeMainAPI("openai");
    const select = document.querySelector<HTMLSelectElement>("#main_api");
    if (select) select.value = "openai";
  }
  const settings = context.chatCompletionSettings;
  settings.chat_completion_source = profile.api;
  if (profile.api === "custom") {
    settings.custom_url = profile["api-url"];
    settings.custom_model = profile.model;
    if (profile["secret-id"]) {
      const secrets = await load("/scripts/secrets.js");
      const r = await fetch("/api/secrets/rotate", {
        method: "POST",
        headers: context.getRequestHeaders(),
        body: JSON.stringify({
          key: secrets.SECRET_KEYS.CUSTOM,
          id: profile["secret-id"],
        }),
      });
      if (!r.ok)
        throw new Error("已保存原生连接，但当前凭据未生效，请手动选中该连接");
      await secrets.readSecretState();
    }
  } else {
    const proxy = openai.proxies.find((p: Data) => p.name === profile.proxy);
    settings.reverse_proxy = proxy?.url || "";
    settings.proxy_password = proxy?.password || "";
    settings[profile.api === "claude" ? "claude_model" : "google_model"] =
      profile.model;
  }
  const fields: Record<string, string> = {
    chat_completion_source: "#chat_completion_source",
    custom_url: "#custom_api_url_text",
    custom_model: "#custom_model_id",
    claude_model: "#model_claude_select",
    google_model: "#model_google_select",
    reverse_proxy: "#openai_reverse_proxy",
    proxy_password: "#openai_proxy_access_key",
  };
  script.setOnlineStatus("资源中心已应用（未探测）");
  for (const [key, selector] of Object.entries(fields)) {
    const input = document.querySelector<HTMLInputElement | HTMLSelectElement>(
      selector,
    );
    if (input) input.value = settings[key] || "";
  }
}
