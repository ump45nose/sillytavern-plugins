const ctx = () => SillyTavern.getContext();
const load = (p) => import(p);
const makeId = () =>
  crypto.randomUUID?.() ||
  Array.from(crypto.getRandomValues(new Uint8Array(16)), (b) => b.toString(16).padStart(2, "0")).join("");
const page = makeId(),
  root = "/api/plugins/resource-center-link";
let status = {},
  working = false,
  applying = false;
const api = async (path, body) => {
  const res = await fetch(root + path, {
    method: body === undefined ? "GET" : "POST",
    headers: ctx().getRequestHeaders(),
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || `请求未完成（${res.status}）`);
  return data;
};
const labels = {
  website: "网站打不开",
  balance: "无余额无签到",
  invalid: "网站或 key 失效",
  unstable: "调用不稳定",
  call: "调用失败",
  maintenance: "暂停维护",
};
const states = {
  applied: "已同步",
  waiting: "待酒馆应用",
  running: "同步中",
  conflict: "配置冲突",
  unresolved: "待补字段",
  failed: "同步失败",
};
const panel = document.createElement("div");
panel.className = "inline-drawer arc-link";
panel.id = "resource-center-link";
panel.innerHTML =
  '<div class="inline-drawer-toggle inline-drawer-header"><b>AI 资源中心联动</b><div class="inline-drawer-icon fa-solid fa-circle-chevron-down down"></div></div><div class="inline-drawer-content"><form data-config><label>资源中心地址<input name="url" class="text_pole" type="url" required placeholder="http://192.168.31.201:18323"></label><label>酒馆实例 ID<input name="instanceId" class="text_pole" value="fn" required></label><label>该实例与用户的 RP 凭据<input name="rpToken" class="text_pole" type="password" autocomplete="off" required></label><label>该实例与用户的配置执行凭据<input name="connectorToken" class="text_pole" type="password" autocomplete="off" required></label><button class="menu_button" type="submit">保存接入</button></form><div data-summary></div><div class="arc-actions"><button class="menu_button" data-sync>立即同步</button><a class="menu_button" data-center target="_blank" rel="noopener">打开资源中心</a></div><div class="arc-error" data-error></div><div class="arc-scroll"><table><thead><tr><th>连接／模型</th><th>状态</th><th>操作</th></tr></thead><tbody data-rows></tbody></table></div></div>';
(document.querySelector("#extensions_settings2") || document.querySelector("#extensions_settings")).append(
  panel,
);
const field = (k) => panel.querySelector(`[name="${k}"]`);
const error = (text) => {
  panel.querySelector("[data-error]").textContent = text || "";
};
function render() {
  panel.querySelector("[data-summary]").textContent = status.configured
    ? `${status.user} · 连接 ${(status.connections || []).length}/${status.inventoryTotal || 0} · 待交 ${status.queue || 0} · 调用待交 ${status.calls || 0} · ${status.lastAck ? "最近确认 " + new Date(status.lastAck).toLocaleString() : "尚未确认"}`
    : "请在中心配对本酒馆实例及用户，并安装配套服务端插件。";
  if (status.url) {
    field("url").value = status.url;
    panel.querySelector("[data-center]").href = status.url;
  }
  if (status.instanceId) field("instanceId").value = status.instanceId;
  const rows = panel.querySelector("[data-rows]");
  rows.replaceChildren();
  for (const c of status.connections || []) {
    const tr = document.createElement("tr"),
      name = document.createElement("td"),
      state = document.createElement("td"),
      actions = document.createElement("td");
    name.textContent = c.name;
    const model = document.createElement("small");
    model.textContent = c.selectedModel || "模型未固定";
    name.append(model);
    state.textContent = c.removed
      ? "永久移除"
      : c.archiveReasons?.map((r) => labels[r]).join("、") || states[c.state] || c.state;
    const accept = document.createElement("small");
    accept.textContent = c.acceptance;
    state.append(accept);
    for (const [label, handler] of c.conflict
      ? [["处理冲突", () => resolve(c)]]
      : [["归档", () => archive([c.nativeConnectionId])]]) {
      const button = document.createElement("button");
      button.className = "menu_button";
      button.textContent = label;
      button.disabled = c.removed || (c.nativeConnectionId === status.selected && label === "归档");
      button.onclick = () => invoke(handler);
      actions.append(button);
    }
    tr.append(name, state, actions);
    rows.append(tr);
  }
  for (const [id, p] of Object.entries(status.problems || {}))
    if (p.error) {
      const tr = document.createElement("tr"),
        td = document.createElement("td");
      td.colSpan = 3;
      const name = ctx().extensionSettings.connectionManager?.profiles?.find((p) => p.id === id)?.name || id;
      td.textContent = `${name}：${p.error}`;
      tr.append(td);
      rows.append(tr);
    }
  if (status.error || status.coverage) error([status.error, status.coverage].filter(Boolean).join("\n"));
}
async function persist() {
  let saved = false;
  const c = ctx(),
    event = c.eventTypes.SETTINGS_UPDATED,
    done = () => {
      saved = true;
    };
  c.eventSource.on(event, done);
  try {
    await (await load("/script.js")).saveSettings();
    if (!saved) throw new Error("酒馆未确认保存，配置保留待应用");
  } finally {
    c.eventSource.removeListener(event, done);
  }
}
async function dialog(title, build) {
  const box = document.createElement("dialog"),
    form = document.createElement("form");
  form.method = "dialog";
  const heading = document.createElement("h3");
  heading.textContent = title;
  form.append(heading);
  const get = build(form);
  const actions = document.createElement("div");
  actions.className = "arc-actions";
  const yes = document.createElement("button");
  yes.className = "menu_button";
  yes.textContent = "保存";
  yes.value = "save";
  const no = document.createElement("button");
  no.className = "menu_button";
  no.textContent = "取消";
  no.value = "cancel";
  no.type = "button";
  no.onclick = () => box.close("cancel");
  actions.append(yes, no);
  form.append(actions);
  box.append(form);
  const wrapper = document.createElement("div");
  wrapper.className = "arc-link";
  wrapper.style.display = "contents";
  wrapper.append(box);
  document.body.append(wrapper);
  return await new Promise((resolve) => {
    box.addEventListener(
      "close",
      () => {
        const result = box.returnValue === "save" ? get() : null;
        wrapper.remove();
        resolve(result);
      },
      { once: true },
    );
    box.showModal();
  });
}
async function archive(ids) {
  const selected = ctx().extensionSettings.connectionManager?.selectedProfile;
  if (ids.includes(selected)) throw new Error("当前连接不能归档，请先选择其他连接");
  const answer = await dialog("选择不可用原因", (form) => {
    const select = document.createElement("select");
    select.className = "text_pole";
    for (const [value, text] of Object.entries(labels)) select.add(new Option(text, value));
    const note = document.createElement("input");
    note.className = "text_pole";
    note.placeholder = "备注（可选）";
    form.append(select, note);
    return () => ({ reason: select.value, note: note.value });
  });
  if (!answer) return { done: [], errors: [] };
  const done = [],
    errors = [];
  for (const id of ids)
    try {
      await api("/archive", { nativeConnectionId: id, ...answer });
      done.push(id);
    } catch (e) {
      errors.push({ id, message: e.message });
    }
  status = await api("/status");
  const prefs = ctx().extensionSettings.resourceCenterLink;
  if (prefs) prefs.visibleArchived = (prefs.visibleArchived || []).filter((id) => !done.includes(id));
  await syncArchives();
  render();
  return { done, errors };
}
async function resolve(c) {
  const answer = await dialog("处理两端配置冲突", (form) => {
    const select = document.createElement("select");
    select.className = "text_pole";
    select.add(new Option("采用资源中心", "center"));
    select.add(new Option("采用酒馆已保存内容", "local"));
    select.add(new Option("逐字段合并", "merge"));
    form.append(select);
    const fields = document.createElement("div"),
      choices = {};
    for (const key of ["name", "selectedModel", "order", "enabled", "note", "baseUrl", "protocol"]) {
      const label = document.createElement("label");
      label.textContent = {
        name: "连接名称",
        selectedModel: "选定模型",
        order: "排序",
        enabled: "绑定启用",
        note: "备注",
        baseUrl: "API 地址",
        protocol: "协议",
      }[key];
      const pick = document.createElement("select");
      pick.className = "text_pole";
      pick.add(new Option("中心：" + String(c.conflict.center[key] ?? ""), "center"));
      pick.add(new Option("酒馆：" + String(c.conflict.local[key] ?? ""), "local"));
      label.append(pick);
      fields.append(label);
      choices[key] = pick;
    }
    const credential = document.createElement("select");
    credential.add(new Option("凭据采用中心", "center"));
    credential.add(new Option("凭据采用酒馆", "local"));
    fields.append(credential);
    fields.hidden = true;
    select.onchange = () => {
      fields.hidden = select.value !== "merge";
    };
    form.append(fields);
    return () => {
      const binding = {},
        channel = {};
      if (select.value === "merge")
        for (const [k, pick] of Object.entries(choices))
          (k === "baseUrl" || k === "protocol" ? channel : binding)[k] = c.conflict[pick.value][k];
      return {
        nativeConnectionId: c.nativeConnectionId,
        resolve: select.value,
        binding,
        channel,
        credentialSide: select.value === "local" ? "local" : credential.value,
      };
    };
  });
  if (answer) {
    status = await api("/resolve", answer);
    render();
  }
}
async function syncArchives() {
  const c = ctx(),
    wb = c.extensionSettings.workbench;
  if (!wb) return;
  const prefs = (c.extensionSettings.resourceCenterLink ??= { bindings: {}, visibleArchived: [] });
  const hidden = new Set(wb.archived?.connection || []),
    selected = c.extensionSettings.connectionManager?.selectedProfile;
  const managed = new Set(prefs.managedArchives || []);
  for (const b of status.connections || []) {
    if (b.removed || b.archiveReasons?.length) {
      if (b.nativeConnectionId !== selected && !prefs.visibleArchived?.includes(b.nativeConnectionId)) {
        hidden.add(b.nativeConnectionId);
        managed.add(b.nativeConnectionId);
      }
    } else if (managed.has(b.nativeConnectionId)) {
      hidden.delete(b.nativeConnectionId);
      managed.delete(b.nativeConnectionId);
    }
  }
  prefs.managedArchives = [...managed];
  const next = [...hidden];
  if (JSON.stringify(next) !== JSON.stringify(wb.archived?.connection || [])) {
    wb.archived = { ...wb.archived, connection: next };
    await persist();
  }
}
async function activate(profile, proxies) {
  const c = ctx(),
    o = c.chatCompletionSettings,
    openai = await load("/scripts/openai.js");
  o.chat_completion_source = profile.api === "google" ? "makersuite" : profile.api;
  if (profile.api === "custom") {
    o.custom_url = profile["api-url"];
    o.custom_model = profile.model;
    if (profile["secret-id"])
      await fetch("/api/secrets/rotate", {
        method: "POST",
        headers: c.getRequestHeaders(),
        body: JSON.stringify({ key: "api_key_custom", id: profile["secret-id"] }),
      }).then((r) => {
        if (!r.ok) throw new Error("原生凭据未确认激活");
      });
  } else {
    const proxy = proxies.find((p) => p.name === profile.proxy);
    o.reverse_proxy = proxy?.url || "";
    o.proxy_password = proxy?.password || "";
    o[profile.api === "claude" ? "claude_model" : "google_model"] = profile.model;
  }
  // Update controls without invoking connection tests or model discovery handlers.
  for (const [id, value] of Object.entries({
    chat_completion_source: o.chat_completion_source,
    custom_api_url_text: o.custom_url,
    custom_model_id: o.custom_model,
    openai_reverse_proxy: o.reverse_proxy,
    openai_proxy_access_key: o.proxy_password,
    model_google_select: o.google_model,
    model_claude_select: o.claude_model,
  })) {
    const el = document.getElementById(id);
    if (el && value !== undefined) el.value = value;
  }
  if (openai.proxies) openai.proxies.splice(0, openai.proxies.length, ...proxies);
  await (await load("/scripts/secrets.js")).readSecretState();
}
async function apply(job) {
  const c = ctx(),
    selected = c.extensionSettings.connectionManager?.selectedProfile;
  if (
    job.payload.nativeConnectionId === selected &&
    (job.payload.removed ||
      job.payload.archiveReasons?.length ||
      job.payload.enabled === false ||
      job.payload.channelEnabled === false)
  ) {
    // Keep the selected Profile available until the user chooses another; guards prevent a new use.
    error("当前连接已归档或停用，请选择其他连接后应用");
    return;
  }
  const prepared = await api("/prepare", { page, id: job.id }),
    cm = c.extensionSettings.connectionManager;
  const index = cm.profiles.findIndex((p) => p.id === prepared.profile.id);
  if (index < 0) throw new Error("原生连接不存在");
  const openai = await load("/scripts/openai.js"),
    before = {
      profiles: structuredClone(cm.profiles),
      proxies: structuredClone(openai.proxies),
      meta: structuredClone(c.extensionSettings.resourceCenterLink || {}),
      api: structuredClone(c.chatCompletionSettings),
    };
  applying = true;
  try {
    cm.profiles.splice(index, 1);
    cm.profiles.splice(Math.min(prepared.snapshot.order, cm.profiles.length), 0, prepared.profile);
    const meta = (c.extensionSettings.resourceCenterLink ??= { bindings: {}, visibleArchived: [] });
    meta.bindings ??= {};
    meta.bindings[prepared.profile.id] = { enabled: prepared.snapshot.enabled, note: prepared.snapshot.note };
    openai.proxies.splice(0, openai.proxies.length, ...prepared.proxies);
    if (selected === prepared.profile.id) await activate(prepared.profile, prepared.proxies);
    const option = [...document.querySelectorAll("#connection_profiles option")].find(
      (o) => o.value === prepared.profile.id,
    );
    if (option) option.textContent = prepared.profile.name;
    await persist();
    await api("/applied", { id: job.id });
    await c.eventSource.emit(c.eventTypes.CONNECTION_PROFILE_UPDATED, prepared.profile);
  } catch (e) {
    // Recover in-memory state only; the server's readback decides whether a successful disk save occurred.
    const actual = await api("/status").catch(() => null);
    if (!actual || actual.queue === 0) {
      cm.profiles = before.profiles;
      openai.proxies.splice(0, openai.proxies.length, ...before.proxies);
      c.extensionSettings.resourceCenterLink = before.meta;
      Object.assign(c.chatCompletionSettings, before.api);
    }
    throw e;
  } finally {
    applying = false;
  }
}
async function legacy() {
  const old = ctx().extensionSettings.aiResourceCenter;
  if (!old?.device) return;
  const prefix = `arc-rp-calls:${old.device}:`,
    entries = [];
  for (let i = 0; i < localStorage.length; i++) {
    const key = localStorage.key(i);
    if (key?.startsWith(prefix))
      try {
        const row = JSON.parse(localStorage.getItem(key));
        if (!row.acknowledged) entries.push(row);
      } catch {}
  }
  if (entries.length) {
    const result = await api("/legacy", { entries });
    for (const id of result.acknowledgedIds) {
      const key = prefix + id,
        row = JSON.parse(localStorage.getItem(key) || "null");
      if (row?.event?.result !== "pending") localStorage.removeItem(key);
    }
  }
}
async function sync() {
  if (working) return;
  working = true;
  error("");
  try {
    status = await api("/status");
    render();
    if (!status.configured) return;
    status = await api("/poll", { page });
    await syncArchives();
    for (const job of status.jobs || [])
      try {
        await apply(job);
      } catch (e) {
        error(e.message);
      }
    await legacy();
    status = await api("/status");
    render();
  } finally {
    working = false;
  }
}
async function run(fn) {
  try {
    return await fn();
  } catch (e) {
    error(e.message);
    throw e;
  }
}
const invoke = (fn) => {
  void run(fn).catch(() => {});
};
panel.querySelector("[data-config]").onsubmit = (event) => {
  event.preventDefault();
  invoke(async () => {
    status = await api("/configure", Object.fromEntries(new FormData(event.target)));
    field("rpToken").value = "";
    field("connectorToken").value = "";
    render();
    await sync();
  });
};
panel.querySelector("[data-sync]").onclick = () => invoke(sync);

// Preserve fetch semantics and attach IDs only to same-origin, actual generation requests.
const original = window.fetch;
window.fetch = function (input, init) {
  try {
    const url = new URL(typeof input === "string" || input instanceof URL ? input : input.url, location.href),
      method = init?.method || input?.method || "GET";
    if (
      url.origin === location.origin &&
      url.pathname === "/api/backends/chat-completions/generate" &&
      method.toUpperCase() === "POST"
    ) {
      const eventId = makeId(),
        headers = new Headers(init?.headers || input?.headers);
      headers.set("X-ARC-Client", "2");
      headers.set("X-ARC-Request-ID", eventId);
      (init?.signal || input?.signal)?.addEventListener(
        "abort",
        () => {
          void api("/cancel", { eventId }).catch(() => {});
        },
        { once: true },
      );
      const id = ctx().extensionSettings.connectionManager?.selectedProfile;
      if (id) headers.set("X-ARC-Profile-ID", id);
      init = { ...init, headers };
    }
  } catch {
    /* observation cannot prevent generation */
  }
  return Reflect.apply(original, this, [input, init]);
};
window.resourceCenterLinkGuard = async (_chat, _contextSize, abort, _type) => {
  const current = ctx().extensionSettings.connectionManager?.selectedProfile,
    c = status.connections?.find((c) => c.nativeConnectionId === current);
  if (c && (c.removed || c.archiveReasons?.length || c.enabled === false || c.channelEnabled === false)) {
    toastr.warning("当前连接已归档或停用，请选择可用连接");
    abort(true);
  }
};
window.addEventListener("workbench:connection-archive-request", (event) => {
  if (!status.configured) return;
  event.preventDefault();
  event.detail.promise = event.detail.on
    ? archive(event.detail.ids)
    : run(async () => {
        const result = await dialog("恢复显示", (form) => {
          const text = document.createElement("p");
          text.textContent =
            "恢复到列表仅改变显示。中心的不可用原因及永久移除状态会保留；需要恢复使用时请在中心处理。";
          form.append(text);
          return () => true;
        });
        if (!result) return { done: [], errors: [] };
        const c = ctx(),
          prefs = (c.extensionSettings.resourceCenterLink ??= { bindings: {}, visibleArchived: [] });
        prefs.visibleArchived = [...new Set([...(prefs.visibleArchived || []), ...event.detail.ids])];
        const hidden = c.extensionSettings.workbench?.archived;
        if (hidden)
          hidden.connection = (hidden.connection || []).filter((id) => !event.detail.ids.includes(id));
        await persist();
        return { done: event.detail.ids, errors: [] };
      });
});
ctx().eventSource.on(ctx().eventTypes.SETTINGS_UPDATED, () => {
  if (!applying)
    void api("/status")
      .then((s) => {
        status = s;
        render();
      })
      .catch(() => {});
});
window.addEventListener("online", () => invoke(sync));
setInterval(() => invoke(sync), 30000);
await run(sync).catch(() => {});
