// src/host/resource-center-calls.ts
var makeId = () => [...crypto.getRandomValues(new Uint8Array(16))].map((x) => x.toString(16).padStart(2, "0")).join("");
var classify = (status, data) => {
  const detail = `${data?.error?.type || ""} ${data?.error?.code || ""} ${data?.error?.message || ""} ${typeof data?.message === "string" ? data.message : ""}`;
  if (status === 429 || /rate.?limit|限流/i.test(detail)) return "rate";
  if (status === 402 || data?.quota_error || /quota|balance|insufficient|余额|额度/i.test(detail))
    return "quota";
  if (status === 401 || /authentication|invalid.*key|invalid.*token/i.test(detail))
    return "key";
  if (status === 403) return "account";
  if (status === 400) return "input";
  return "upstream";
};
var RpCallOutbox = class {
  constructor(settings2, request, storage, refresh2) {
    this.settings = settings2;
    this.request = request;
    this.storage = storage;
    this.refresh = refresh2;
  }
  delivering = false;
  error = "";
  lastAck = "";
  prefix() {
    return `arc-rp-calls:${this.settings().device}:`;
  }
  entries() {
    const rows = [];
    for (let i = 0; i < this.storage.length; i++) {
      const key = this.storage.key(i);
      const value = key && key.startsWith(this.prefix()) ? this.storage.getItem(key) : null;
      if (value) rows.push(JSON.parse(value));
    }
    return rows.sort(
      (a, b) => a.event.occurredAt.localeCompare(b.event.occurredAt)
    );
  }
  put(event) {
    try {
      const row = {
        device: this.settings().device,
        event,
        revision: event.result === "pending" ? 1 : 2,
        acknowledged: false
      };
      this.storage.setItem(this.prefix() + event.eventId, JSON.stringify(row));
      this.refresh();
      void this.deliver();
    } catch (e) {
      this.error = `\u8C03\u7528\u8BB0\u5F55\u672A\u80FD\u4FDD\u5B58\uFF1A${String(e)}`;
      this.refresh();
    }
  }
  async deliver() {
    if (this.delivering || !this.settings().url || !this.settings().token)
      return;
    this.delivering = true;
    try {
      for (const row of this.entries().filter((r) => !r.acknowledged)) {
        const result = await this.request("calls", {
          device: row.device,
          events: [row.event]
        });
        if (!result.acknowledgedIds?.includes(row.event.eventId))
          throw new Error("\u4E2D\u5FC3\u672A\u786E\u8BA4\u8C03\u7528\u8BB0\u5F55");
        const key = this.prefix() + row.event.eventId, current = this.storage.getItem(key);
        if (current && JSON.parse(current).revision === row.revision) {
          if (row.event.result === "pending")
            this.storage.setItem(
              key,
              JSON.stringify({ ...row, acknowledged: true })
            );
          else this.storage.removeItem(key);
        }
        this.error = "";
        this.lastAck = (/* @__PURE__ */ new Date()).toISOString();
      }
    } catch (e) {
      this.error = String(e);
    } finally {
      this.delivering = false;
      this.refresh();
      if (!this.error && this.entries().some((r) => !r.acknowledged))
        void this.deliver();
    }
  }
};
var ResponseFacts = class {
  constructor(started, now, finish) {
    this.started = started;
    this.now = now;
    this.finish = finish;
  }
  inputTokens;
  outputTokens;
  ttft;
  terminal = false;
  sawSseData = false;
  decoder = new TextDecoder();
  buffer = "";
  data = "";
  oversized = false;
  lineOversized = false;
  inspect(d) {
    if (!d || typeof d !== "object") return;
    const usage = d.usage || d.message?.usage || d.response?.usage;
    const gemini = d.usageMetadata;
    const input = usage?.prompt_tokens ?? usage?.input_tokens ?? gemini?.promptTokenCount;
    const output = usage?.completion_tokens ?? usage?.output_tokens ?? gemini?.candidatesTokenCount;
    if (Number.isFinite(input) && input >= 0) this.inputTokens = input;
    if (Number.isFinite(output) && output >= 0) this.outputTokens = output;
    const delta = d.choices?.[0]?.delta;
    const first = delta?.content || delta?.reasoning_content || delta?.reasoning || delta?.tool_calls?.length || d.delta?.text || d.delta?.thinking || d.delta?.partial_json || d.type === "response.output_text.delta" && d.delta || d.candidates?.[0]?.content?.parts?.some(
      (p) => p.text || p.functionCall
    );
    if (first && this.ttft === void 0) this.ttft = this.now() - this.started;
    if (d.error || d.quota_error || d.type === "error" || d.type === "response.failed") {
      this.finish("failure", classify(0, d));
      return;
    }
    if (d.type === "message_stop") {
      this.terminal = true;
      this.finish("success");
    }
    if (d.type === "response.completed" || d.choices?.some((c2) => c2.finish_reason) || d.candidates?.some((c2) => c2.finishReason))
      this.terminal = true;
  }
  line(line) {
    if (!line) {
      if (!this.oversized && this.data) {
        const raw = this.data.slice(0, -1);
        if (raw === "[DONE]") {
          this.terminal = true;
          this.finish("success");
        } else {
          try {
            this.inspect(JSON.parse(raw));
          } catch {
          }
        }
      }
      this.data = "";
      this.oversized = false;
    } else if (!this.oversized && line.startsWith("data:")) {
      this.sawSseData = true;
      this.data += line.slice(5).replace(/^ /, "") + "\n";
      if (this.data.length > 512 * 1024) {
        this.data = "";
        this.oversized = true;
      }
    }
  }
  chunk(bytes) {
    this.buffer += this.decoder.decode(bytes, { stream: true });
    let end;
    while ((end = this.buffer.indexOf("\n")) >= 0) {
      const line = this.buffer.slice(0, end).replace(/\r$/, "");
      this.buffer = this.buffer.slice(end + 1);
      if (this.lineOversized) {
        this.lineOversized = false;
        this.oversized = true;
      } else this.line(line);
    }
    if (this.buffer.length > 512 * 1024) {
      this.buffer = "";
      this.lineOversized = true;
    }
  }
  end() {
    this.buffer += this.decoder.decode();
    if (this.buffer && !this.lineOversized)
      this.line(this.buffer.replace(/\r$/, ""));
    this.line("");
    this.finish(this.terminal ? "success" : "unknown");
  }
};
function observeRpCalls(host, snapshot, report, onError, now = () => performance.now()) {
  const original = host.fetch;
  const paths = /* @__PURE__ */ new Set([
    "/api/backends/chat-completions/generate",
    "/api/backends/text-completions/generate"
  ]);
  host.fetch = function(input, init) {
    let event;
    try {
      const url = new URL(
        typeof input === "string" || input instanceof URL ? String(input) : input.url,
        host.location.href
      );
      if (url.origin === host.location.origin && paths.has(url.pathname) && (init?.method || "GET").toUpperCase() === "POST" && typeof init?.body === "string") {
        const body = JSON.parse(init.body), meta = snapshot(body);
        if (meta)
          event = {
            ...meta,
            eventId: makeId(),
            model: String(body.model || ""),
            isStream: !!body.stream,
            origin: "live",
            occurredAt: (/* @__PURE__ */ new Date()).toISOString(),
            result: "pending"
          };
      }
    } catch (e) {
      onError(e);
    }
    if (!event) return Reflect.apply(original, this, [input, init]);
    const call = event, started = now();
    let finished = false;
    const safeReport = (e) => {
      try {
        report(e);
      } catch (error) {
        onError(error);
      }
    };
    const facts = new ResponseFacts(started, now, finish);
    const abort = () => finish("cancelled", "cancelled");
    init?.signal?.addEventListener("abort", abort, { once: true });
    function finish(result, errorType) {
      if (finished) return;
      finished = true;
      init?.signal?.removeEventListener("abort", abort);
      safeReport({
        ...call,
        result,
        latency: now() - started,
        ...facts.ttft !== void 0 ? { ttft: facts.ttft } : {},
        ...facts.inputTokens !== void 0 ? { inputTokens: facts.inputTokens } : {},
        ...facts.outputTokens !== void 0 ? { outputTokens: facts.outputTokens } : {},
        ...facts.inputTokens !== void 0 || facts.outputTokens !== void 0 ? { tokenBasis: "provider" } : {},
        ...errorType ? { errorType } : {},
        ...call.isStream ? {
          streamStatus: result === "success" ? "completed" : result === "cancelled" ? "cancelled" : result === "failure" ? "disconnected" : "unknown"
        } : {}
      });
    }
    safeReport({ ...call });
    let request;
    try {
      request = Reflect.apply(original, this, [input, init]);
    } catch (e) {
      finish("failure", "upstream");
      throw e;
    }
    return request.then(
      (response) => {
        call.statusCode = response.status;
        if (!response.ok || !call.isStream) {
          const json = response.json.bind(response), text = response.text.bind(response);
          const inspect = (data) => {
            if (!response.ok)
              finish("failure", classify(response.status, data));
            else {
              facts.inspect(data);
              finish(
                data?.choices?.length || data?.content?.length || data?.candidates?.length || data?.output?.length ? "success" : "unknown"
              );
            }
          };
          const rejected = (e) => {
            finish(
              e?.name === "AbortError" ? "cancelled" : "failure",
              e?.name === "AbortError" ? "cancelled" : "upstream"
            );
            throw e;
          };
          response.json = async () => {
            try {
              const data = await json();
              inspect(data);
              return data;
            } catch (e) {
              return rejected(e);
            }
          };
          response.text = async () => {
            try {
              const raw = await text();
              let data;
              if (raw.length <= 512 * 1024) {
                try {
                  data = JSON.parse(raw);
                } catch {
                }
              }
              inspect(data);
              return raw;
            } catch (e) {
              return rejected(e);
            }
          };
          return response;
        }
        if (!response.body) {
          finish("unknown");
          return response;
        }
        const reader = response.body.getReader();
        let errorJson = "";
        const stream = new ReadableStream({
          async pull(controller) {
            try {
              const { value, done } = await reader.read();
              if (done) {
                if (!facts.sawSseData) {
                  try {
                    facts.inspect(JSON.parse(errorJson));
                  } catch {
                  }
                }
                facts.end();
                controller.close();
              } else {
                facts.chunk(value);
                if (!facts.sawSseData && errorJson.length < 512 * 1024)
                  errorJson += new TextDecoder().decode(
                    value.subarray(0, 512 * 1024 - errorJson.length)
                  );
                controller.enqueue(value);
              }
            } catch (e) {
              finish(
                e.name === "AbortError" ? "cancelled" : "failure",
                e.name === "AbortError" ? "cancelled" : "upstream"
              );
              controller.error(e);
            }
          },
          cancel(reason) {
            finish("cancelled", "cancelled");
            return reader.cancel(reason);
          }
        });
        return new Response(stream, {
          status: response.status,
          statusText: response.statusText,
          headers: response.headers
        });
      },
      (error) => {
        finish(
          error?.name === "AbortError" ? "cancelled" : "failure",
          error?.name === "AbortError" ? "cancelled" : "upstream"
        );
        throw error;
      }
    );
  };
  return () => {
    host.fetch = original;
  };
}

// src/host/resource-center.ts
var randomId = () => [...crypto.getRandomValues(new Uint8Array(16))].map((x) => x.toString(16).padStart(2, "0")).join("");
var centerDefaults = () => ({
  url: "",
  token: "",
  device: randomId(),
  bindings: {},
  outbox: []
});
function profileConnection(profile, proxies) {
  const protocol = profile.api === "claude" ? "Anthropic" : profile.api === "makersuite" ? "Gemini" : "OpenAI";
  const baseUrl = protocol === "OpenAI" ? profile["api-url"] : proxies.find((p) => p.name === profile.proxy)?.url;
  if (!baseUrl || !/^https?:\/\//.test(baseUrl))
    throw new Error("\u8BE5\u539F\u751F\u8FDE\u63A5\u5C1A\u65E0\u660E\u786E API \u5730\u5740\uFF0C\u8BF7\u5148\u5728\u9152\u9986\u4FDD\u5B58\u5730\u5740");
  return {
    name: profile.name,
    baseUrl,
    protocol,
    models: [String(profile.model || "")].filter(Boolean)
  };
}
var ResourceCenterLink = class {
  constructor(settings2, profiles2, proxies, persist2, refresh2, selected2) {
    this.settings = settings2;
    this.profiles = profiles2;
    this.proxies = proxies;
    this.persist = persist2;
    this.refresh = refresh2;
    this.selected = selected2;
  }
  delivering = false;
  persisting = false;
  saves = Promise.resolve();
  connections = [];
  async request(path, body) {
    const s = this.settings();
    if (!s.url || !s.token) throw new Error("\u8BF7\u5148\u8BBE\u7F6E\u8D44\u6E90\u4E2D\u5FC3\u5730\u5740\u4E0E RP \u51ED\u636E");
    const r = await fetch(s.url.replace(/\/$/, "") + "/api/v1/rp/" + path, {
      method: body ? "POST" : "GET",
      headers: {
        "Content-Type": "application/json",
        Authorization: "Bearer " + s.token
      },
      ...body ? { body: JSON.stringify(body) } : {},
      signal: AbortSignal.timeout(15e3)
    });
    const result = await r.json();
    if (!r.ok) throw new Error(result.error || `\u8D44\u6E90\u4E2D\u5FC3 HTTP ${r.status}`);
    return result;
  }
  async saveSettings() {
    this.persisting = true;
    const run = this.saves.catch(() => {
    }).then(() => this.persist());
    this.saves = run;
    try {
      await run;
    } finally {
      if (this.saves === run) this.persisting = false;
    }
    this.refresh();
  }
  async read() {
    try {
      this.connections = await this.request("connections");
      this.settings().error = void 0;
    } catch (e) {
      this.settings().error = e instanceof Error ? e.message : String(e);
    }
    this.refresh();
  }
  async queueSavedProfiles() {
    if (this.persisting) return;
    const s = this.settings();
    if (!s.url || !s.token) return;
    let changed = false;
    for (const [profileId, binding] of Object.entries(s.bindings)) {
      const profile = this.profiles().find((p) => p.id === profileId);
      if (!profile) continue;
      const patch = profileConnection(profile, this.proxies()), current = this.selected() === profileId;
      const signature = JSON.stringify([patch, current]);
      if (signature === binding.signature) continue;
      if (s.outbox.length >= 2e3)
        throw new Error("RP \u4E0A\u62A5\u961F\u5217\u5DF2\u6EE1\uFF0C\u8BF7\u5148\u5904\u7406\u540C\u6B65\u9519\u8BEF\uFF1B\u539F\u751F\u4FDD\u5B58\u4E0D\u53D7\u5F71\u54CD");
      s.outbox.push({
        eventId: randomId(),
        profileId,
        channelId: binding.channelId,
        expectedVersion: binding.version,
        patch,
        current
      });
      binding.signature = signature;
      changed = true;
    }
    if (changed) {
      await this.saveSettings();
      await this.deliver();
    }
  }
  async deliver() {
    if (this.delivering) return;
    this.delivering = true;
    const s = this.settings();
    try {
      while (s.outbox.length) {
        const event = s.outbox[0];
        const result = await this.request(event.channelId + "/saved", {
          ...event,
          device: s.device
        });
        const binding = s.bindings[event.profileId];
        if (binding) binding.version = result.acceptedVersion;
        s.outbox = s.outbox.filter((x) => x.eventId !== event.eventId);
        for (const queued of s.outbox)
          if (queued.channelId === event.channelId && queued.expectedVersion === event.expectedVersion)
            queued.expectedVersion = result.acceptedVersion;
        s.lastAck = (/* @__PURE__ */ new Date()).toISOString();
        s.error = void 0;
        await this.saveSettings();
      }
    } catch (e) {
      s.error = e instanceof Error ? e.message : String(e);
      await this.saveSettings();
    } finally {
      this.delivering = false;
      this.refresh();
    }
  }
};

// src/host/resource-center-native.ts
var load = (path) => import(
  /* @vite-ignore */
  path
);
async function applyNativeConnection(current, remote, context, openai2) {
  const patch = {
    ...current,
    name: remote.name,
    model: remote.models[0]
  };
  if (remote.protocol === "OpenAI") {
    patch.api = "custom";
    patch["api-url"] = remote.baseUrl;
    if (remote.key) {
      const secrets = await load("/scripts/secrets.js"), key = secrets.SECRET_KEYS.CUSTOM;
      const native = async (path, body) => {
        const r = await fetch("/api/secrets/" + path, {
          method: "POST",
          headers: context.getRequestHeaders(),
          ...body ? { body: JSON.stringify(body) } : {}
        });
        if (!r.ok) throw new Error("\u539F\u751F\u51ED\u636E " + path + " \u4FDD\u5B58\u5931\u8D25");
        return path === "rotate" ? null : r.json();
      };
      const before = await native("read"), active = before[key]?.find((x) => x.active)?.id;
      const { id } = await native("write", {
        key,
        value: remote.key,
        label: `\u8D44\u6E90\u4E2D\u5FC3 ${current.id}`
      });
      if (!id) throw new Error("\u539F\u751F\u51ED\u636E\u672A\u786E\u8BA4\u4FDD\u5B58");
      if (active) await native("rotate", { key, id: active });
      await secrets.readSecretState();
      patch["secret-id"] = id;
    }
  } else if (["Anthropic", "Gemini"].includes(remote.protocol)) {
    patch.api = remote.protocol === "Anthropic" ? "claude" : "makersuite";
    const name = `\u8D44\u6E90\u4E2D\u5FC3 ${current.id}`, previous = openai2.proxies.find((p) => p.name === current.proxy);
    let proxy = openai2.proxies.find((p) => p.name === name);
    if (!proxy) {
      proxy = {
        name,
        url: remote.baseUrl,
        password: remote.key || previous?.password || ""
      };
      openai2.proxies.push(proxy);
    } else {
      proxy.url = remote.baseUrl;
      if (remote.key) proxy.password = remote.key;
    }
    patch.proxy = name;
    const select = document.querySelector(
      "#openai_proxy_preset"
    );
    if (select && ![...select.options].some((o) => o.value === name)) {
      const option = document.createElement("option");
      option.value = name;
      option.textContent = name;
      select.append(option);
    }
  } else throw new Error("\u8BE5\u539F\u751F\u534F\u8BAE\u5C1A\u4E0D\u652F\u6301\u4FDD\u5B58\uFF0C\u8BF7\u5728\u9152\u9986\u624B\u52A8\u7EF4\u62A4");
  return patch;
}
async function activateSavedConnection(profile, context, openai2) {
  const script2 = await load("/script.js");
  if (context.mainApi !== "openai") {
    script2.changeMainAPI("openai");
    const select = document.querySelector("#main_api");
    if (select) select.value = "openai";
  }
  const settings2 = context.chatCompletionSettings;
  settings2.chat_completion_source = profile.api;
  if (profile.api === "custom") {
    settings2.custom_url = profile["api-url"];
    settings2.custom_model = profile.model;
    if (profile["secret-id"]) {
      const secrets = await load("/scripts/secrets.js");
      const r = await fetch("/api/secrets/rotate", {
        method: "POST",
        headers: context.getRequestHeaders(),
        body: JSON.stringify({
          key: secrets.SECRET_KEYS.CUSTOM,
          id: profile["secret-id"]
        })
      });
      if (!r.ok)
        throw new Error("\u5DF2\u4FDD\u5B58\u539F\u751F\u8FDE\u63A5\uFF0C\u4F46\u5F53\u524D\u51ED\u636E\u672A\u751F\u6548\uFF0C\u8BF7\u624B\u52A8\u9009\u4E2D\u8BE5\u8FDE\u63A5");
      await secrets.readSecretState();
    }
  } else {
    const proxy = openai2.proxies.find((p) => p.name === profile.proxy);
    settings2.reverse_proxy = proxy?.url || "";
    settings2.proxy_password = proxy?.password || "";
    settings2[profile.api === "claude" ? "claude_model" : "google_model"] = profile.model;
  }
  const fields = {
    chat_completion_source: "#chat_completion_source",
    custom_url: "#custom_api_url_text",
    custom_model: "#custom_model_id",
    claude_model: "#model_claude_select",
    google_model: "#model_google_select",
    reverse_proxy: "#openai_reverse_proxy",
    proxy_password: "#openai_proxy_access_key"
  };
  script2.setOnlineStatus("\u8D44\u6E90\u4E2D\u5FC3\u5DF2\u5E94\u7528\uFF08\u672A\u63A2\u6D4B\uFF09");
  for (const [key, selector] of Object.entries(fields)) {
    const input = document.querySelector(
      selector
    );
    if (input) input.value = settings2[key] || "";
  }
}

// src/rp-entry.ts
var load2 = (path) => import(
  /* @vite-ignore */
  path
);
var ctx = () => window.SillyTavern.getContext();
var openai = await load2("/scripts/openai.js");
var script = await load2("/script.js");
var settings = () => {
  const c2 = ctx();
  c2.extensionSettings.aiResourceCenter ??= centerDefaults();
  return c2.extensionSettings.aiResourceCenter;
};
var profiles = () => ctx().extensionSettings.connectionManager?.profiles || [];
var selected = () => ctx().extensionSettings.connectionManager?.selectedProfile || "";
var generating = false;
var persist = async () => {
  let confirmed = false;
  const c2 = ctx(), event = c2.eventTypes.SETTINGS_UPDATED;
  const done = () => {
    confirmed = true;
  };
  c2.eventSource.on(event, done);
  try {
    await script.saveSettings();
    if (!confirmed) throw new Error("\u539F\u751F\u8BBE\u7F6E\u4FDD\u5B58\u672A\u786E\u8BA4");
  } finally {
    c2.eventSource.removeListener(event, done);
  }
};
var panel = document.createElement("div");
panel.className = "inline-drawer";
panel.id = "ai-resource-center-rp";
panel.innerHTML = '<div class="inline-drawer-toggle inline-drawer-header"><b>AI \u8D44\u6E90\u4E2D\u5FC3 \xB7 RP</b><div class="inline-drawer-icon fa-solid fa-circle-chevron-down down"></div></div><div class="inline-drawer-content"><label>\u4E2D\u5FC3\u5730\u5740<input data-field="url" class="text_pole" placeholder="http://192.168.31.201:18321"></label><label>\u9650\u5B9A RP \u8FDE\u63A5\u7684\u51ED\u636E<input data-field="token" type="password" class="text_pole" autocomplete="off"></label><button data-action="configure" class="menu_button">\u4FDD\u5B58\u5E76\u8BFB\u53D6</button><button data-action="read" class="menu_button">\u8BFB\u53D6\u4E2D\u5FC3</button><div data-state style="white-space:pre-wrap;overflow-wrap:anywhere"></div><label>\u7ED1\u5B9A\u5F53\u524D\u9152\u9986\u8FDE\u63A5<select data-channels class="text_pole"></select></label><button data-action="bind" class="menu_button">\u5173\u8054\u5F53\u524D\u8FDE\u63A5</button><button data-action="apply" class="menu_button">\u5E94\u7528\u4E2D\u5FC3\u914D\u7F6E\u5230\u539F\u751F\u8FDE\u63A5</button><button data-action="send" class="menu_button">\u4E0A\u62A5\u9152\u9986\u5DF2\u4FDD\u5B58\u914D\u7F6E</button><button data-action="retry" class="menu_button">\u91CD\u4EA4\u4FDD\u5B58\u7ED3\u679C</button><div data-calls style="white-space:pre-wrap;overflow-wrap:anywhere"></div><button data-action="calls" class="menu_button">\u91CD\u4EA4\u8C03\u7528\u8BB0\u5F55</button><div data-error style="color:#f58a86;white-space:pre-wrap"></div><small>\u771F\u5B9E\u8C03\u7528\u81EA\u52A8\u4E0A\u62A5\uFF1B\u4FDD\u5B58\u548C\u540C\u6B65\u4E0D\u6D4B\u6D3B\u3002\u6682\u505C\u4ECE\u4E0B\u4E00\u6B21\u751F\u6210\u751F\u6548\u3002</small></div>';
var container = document.querySelector("#extensions_settings2") || document.querySelector("#extensions_settings");
if (!container) throw new Error("\u7F3A\u5C11\u9152\u9986\u6269\u5C55\u8BBE\u7F6E\u5165\u53E3");
container.append(panel);
var field = (name) => panel.querySelector(`[data-field="${name}"]`);
field("url").value = settings().url;
field("token").value = settings().token;
var connectionSelect = panel.querySelector("[data-channels]");
var refresh = () => {
  const s = settings(), profile = profiles().find((p) => p.id === selected()), binding = s.bindings[selected()], remote = link.connections.find((c2) => c2.id === binding?.channelId);
  panel.querySelector("[data-state]").textContent = `\u5F53\u524D\uFF1A${profile?.name || "\u672A\u9009\u62E9\u539F\u751F\u8FDE\u63A5"}
${binding ? `\u9152\u9986 v${binding.version} \xB7 ${binding.enabled ? "\u542F\u7528" : "\u6682\u505C"} \xB7 \u7981\u6D4B\u6D3B` : "\u5C1A\u672A\u7ED1\u5B9A"}${remote ? `
\u4E2D\u5FC3 v${remote.version}\uFF1A${remote.baseUrl} \xB7 ${remote.models.join(", ")}` : ""}
\u5F85\u4EA4\u4FDD\u5B58 ${s.outbox.length} \u6761 \xB7 \u6700\u8FD1\u786E\u8BA4 ${s.lastAck || "\u65E0"}`;
  panel.querySelector("[data-error]").textContent = s.error || "";
  const rows = calls.entries();
  panel.querySelector("[data-calls]").textContent = `\u8C03\u7528\uFF1A\u5F85\u4EA4 ${rows.filter((r) => !r.acknowledged).length} \u6761 \xB7 \u5F85\u7EC8\u6001 ${rows.filter((r) => r.event.result === "pending").length} \u6761
\u6700\u8FD1\u8C03\u7528\u786E\u8BA4 ${calls.lastAck || "\u65E0"}${calls.error ? "\n" + calls.error : ""}`;
  const value = connectionSelect.value;
  connectionSelect.replaceChildren(
    new Option("\u8BF7\u9009\u62E9", ""),
    ...link.connections.map(
      (c2) => new Option(`${c2.name} \xB7 ${c2.baseUrl}`, c2.id)
    )
  );
  connectionSelect.value = value;
};
var link = new ResourceCenterLink(
  settings,
  profiles,
  () => openai.proxies,
  persist,
  refresh,
  selected
);
var calls = new RpCallOutbox(
  settings,
  (path, body) => link.request(path, body),
  localStorage,
  refresh
);
observeRpCalls(
  window,
  (body) => {
    const s = settings();
    if (!s.url || !s.token) return null;
    const profileId = selected(), source = body.chat_completion_source;
    const protocol = source === "claude" ? "Anthropic" : ["makersuite", "vertexai"].includes(source) ? "Gemini" : source ? "OpenAI" : void 0;
    const address = (source === "custom" ? body.custom_url : body.reverse_proxy) || body.api_server;
    let baseUrl;
    if (address) {
      const u = new URL(address);
      u.username = "";
      u.password = "";
      u.search = "";
      u.hash = "";
      baseUrl = u.href;
    }
    return {
      profileId: profileId || void 0,
      channelId: s.bindings[profileId]?.channelId,
      baseUrl,
      protocol
    };
  },
  (event) => calls.put(event),
  (error) => {
    calls.error = `\u8C03\u7528\u91C7\u96C6\uFF1A${String(error)}`;
    refresh();
  }
);
setInterval(() => void calls.deliver(), 3e4);
var apply = async () => {
  if (generating || ctx().streamingProcessor)
    throw new Error("\u8BF7\u5728\u5F53\u524D\u751F\u6210\u7ED3\u675F\u540E\u5E94\u7528");
  const id = selected(), s = settings(), binding = s.bindings[id], current = profiles().find((p) => p.id === id);
  if (!binding || !current) throw new Error("\u8BF7\u5148\u7ED1\u5B9A\u5F53\u524D\u539F\u751F\u8FDE\u63A5");
  const remote = await link.request(binding.channelId + "/config");
  const patch = await applyNativeConnection(current, remote, ctx(), openai);
  await activateSavedConnection(patch, ctx(), openai);
  Object.assign(current, patch);
  binding.version = remote.version;
  binding.enabled = remote.enabled;
  binding.signature = void 0;
  s.outbox = s.outbox.filter((e) => e.profileId !== id);
  const option = document.querySelector(
    `#connection_profiles option[value="${CSS.escape(id)}"]`
  );
  if (option) option.textContent = patch.name;
  await persist();
  await link.queueSavedProfiles();
  await link.read();
};
var busy = false;
panel.addEventListener("click", async (event) => {
  const button = event.target.closest(
    "button[data-action]"
  );
  if (!button || busy) return;
  busy = true;
  panel.querySelectorAll("button[data-action]").forEach((b) => b.disabled = true);
  try {
    const s = settings();
    if (button.dataset.action === "configure") {
      s.url = field("url").value.trim();
      s.token = field("token").value.trim();
      await link.saveSettings();
      await link.read();
    }
    if (button.dataset.action === "read") await link.read();
    if (button.dataset.action === "bind") {
      const profile = profiles().find((p) => p.id === selected()), remote = link.connections.find((c2) => c2.id === connectionSelect.value);
      if (!profile || !remote) throw new Error("\u8BF7\u9009\u62E9\u539F\u751F\u8FDE\u63A5\u548C\u4E2D\u5FC3 RP \u8FDE\u63A5");
      s.bindings[profile.id] = {
        channelId: remote.id,
        version: remote.version,
        enabled: remote.enabled,
        signature: JSON.stringify([
          profileConnection(profile, openai.proxies),
          true
        ])
      };
      await link.saveSettings();
    }
    if (button.dataset.action === "apply") await apply();
    if (button.dataset.action === "send") {
      const b = s.bindings[selected()];
      if (!b) throw new Error("\u5C1A\u672A\u7ED1\u5B9A");
      b.signature = void 0;
      await link.queueSavedProfiles();
    }
    if (button.dataset.action === "retry") await link.deliver();
    if (button.dataset.action === "calls") await calls.deliver();
  } catch (e) {
    settings().error = e instanceof Error ? e.message : String(e);
  } finally {
    busy = false;
    panel.querySelectorAll("button[data-action]").forEach((b) => b.disabled = false);
    refresh();
  }
});
var c = ctx();
c.eventSource.on(c.eventTypes.SETTINGS_UPDATED, () => {
  if (!link.persisting)
    void link.queueSavedProfiles().catch((e) => {
      settings().error = String(e);
      refresh();
    });
});
c.eventSource.on(
  c.eventTypes.GENERATION_STARTED,
  (_type, _options, dry) => {
    if (!dry) generating = true;
  }
);
for (const name of ["GENERATION_ENDED", "GENERATION_STOPPED"])
  c.eventSource.on(c.eventTypes[name], () => {
    generating = false;
  });
c.eventSource.on(c.eventTypes.CONNECTION_PROFILE_LOADED, () => {
  refresh();
});
window.addEventListener("online", () => {
  void link.deliver();
  void calls.deliver();
});
globalThis.aiResourceCenterRpGuard = (_chat, _size, abort) => {
  if (settings().bindings[selected()]?.enabled === false) {
    abort(true);
    generating = false;
    settings().error = "\u5F53\u524D RP \u8FDE\u63A5\u5DF2\u6682\u505C\uFF0C\u8BF7\u5728\u8D44\u6E90\u4E2D\u5FC3\u6062\u590D\u6216\u9009\u62E9\u5176\u4ED6\u8FDE\u63A5";
    refresh();
  }
};
refresh();
if (settings().url) {
  void link.deliver();
  void calls.deliver();
}
//# sourceMappingURL=index.js.map
