import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { randomUUID } from "node:crypto";
import { Journal } from "./journal.mjs";
import { inventory, readSettings, requestFacts, nativePatch, canonical } from "./native.mjs";
import { ResponseFacts } from "./facts.mjs";

export const info = {
  id: "resource-center-link",
  name: "AI 资源中心联动",
  description: "原生连接双向同步、凭据交付及真实调用元数据采集",
};
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
const cleanError = (e) =>
  e?.status
    ? `中心请求未完成（HTTP ${e.status}）`
    : String(e?.message || "操作未完成")
        .replace(/\bsk-[\w-]+/g, "[凭据已隐藏]")
        .slice(0, 200);
const sessions = new Map();
const detach = [];
let timer;
let host;
function serverRoot() {
  for (const dir of [process.argv[1] && path.dirname(fs.realpathSync(process.argv[1])), process.cwd()])
    if (dir && fs.existsSync(path.join(dir, "src/endpoints/secrets.js"))) return dir;
  throw new Error("找不到酒馆运行目录");
}
function attach(router, handler) {
  const before = router.stack.length;
  router.use(handler);
  const added = router.stack.splice(before);
  router.stack.unshift(...added);
  detach.push(() => {
    for (const layer of added) {
      const i = router.stack.indexOf(layer);
      if (i >= 0) router.stack.splice(i, 1);
    }
  });
}
class Session {
  constructor(dirs, user) {
    this.dirs = dirs;
    this.user = user;
    this.journal = new Journal(dirs.root);
    this.s = this.journal.state;
    this.busy = false;
    this.active = 0;
    for (const row of Object.values(this.s.calls))
      if (row.event.result === "pending") {
        row.event.result = "unknown";
        row.event.streamStatus = "unknown";
        row.revision++;
        row.acknowledged = false;
      }
    if (this.s.config) this.journal.save();
  }
  save() {
    this.journal.save();
  }
  manager() {
    return new host.secrets.SecretManager(this.dirs);
  }
  native() {
    const settings = readSettings(this.dirs),
      rows = inventory(settings, this.dirs, this.manager());
    const meta = settings.extension_settings?.resourceCenterLink?.bindings || {};
    for (const p of rows)
      if (p.snapshot) {
        p.snapshot.enabled = meta[p.nativeConnectionId]?.enabled !== false;
        p.snapshot.note = meta[p.nativeConnectionId]?.note || "";
      }
    return { settings, rows };
  }
  enqueue(kind, body, extra = {}) {
    this.s.queue.push({ kind, eventId: randomUUID(), body, ...extra });
    this.save();
  }
  observe() {
    if (!this.s.config) return;
    const { rows } = this.native(),
      known = this.s.observed;
    if (!this.s.legacySavesImported) {
      const legacy = readSettings(this.dirs).extension_settings?.aiResourceCenter?.outbox || [];
      for (const entry of legacy)
        if (entry.eventId && entry.profileId && entry.patch) {
          this.s.queue.push({ kind: "legacy-save", eventId: entry.eventId, body: structuredClone(entry) });
        }
      this.s.legacySavesImported = true;
      this.save();
    }
    if (!this.s.registered) {
      if (!this.s.queue.some((x) => x.kind === "inventory"))
        this.enqueue(
          "inventory",
          { profiles: rows.map(({ credential, ...p }) => p), removedIds: [] },
          { credentials: Object.fromEntries(rows.map((p) => [p.nativeConnectionId, p.credential])) },
        );
      this.s.observed = Object.fromEntries(rows.map((p) => [p.nativeConnectionId, p.snapshot]));
      this.save();
      return;
    }
    const pendingInventory = new Set(
      this.s.queue
        .filter((q) => q.kind === "inventory")
        .flatMap((q) => q.body.profiles.map((p) => p.nativeConnectionId)),
    );
    const unknown = rows.filter(
      (p) =>
        p.snapshot && !this.s.mappings[p.nativeConnectionId] && !pendingInventory.has(p.nativeConnectionId),
    );
    if (unknown.length)
      this.enqueue(
        "inventory",
        { profiles: unknown.map(({ credential, ...p }) => p), removedIds: [] },
        { credentials: Object.fromEntries(unknown.map((p) => [p.nativeConnectionId, p.credential])) },
      );
    for (const p of rows) {
      if (!p.snapshot) {
        this.s.problems[p.nativeConnectionId] = { error: p.error };
        continue;
      }
      const prepared = this.s.prepared;
      if (prepared?.nativeConnectionId === p.nativeConnectionId && same(prepared.snapshot, p.snapshot)) {
        this.s.completed ??= {};
        this.s.completed[prepared.job.id] = { snapshot: p.snapshot };
        if (!this.s.queue.some((q) => q.kind === "receipt" && q.body.id === prepared.job.id))
          this.enqueue("receipt", {
            id: prepared.job.id,
            lease: prepared.job.lease,
            state: "applied",
            remoteId: p.nativeConnectionId,
            snapshot: p.snapshot,
          });
        this.s.prepared = null;
      } else if (
        Object.hasOwn(known, p.nativeConnectionId) &&
        !same(known[p.nativeConnectionId], p.snapshot)
      ) {
        const b = this.s.mappings[p.nativeConnectionId];
        this.enqueue(
          "save",
          {
            nativeConnectionId: p.nativeConnectionId,
            localRevision: ++this.s.localRevision,
            snapshot: p.snapshot,
            baseChannelVersion: b?.channelVersion,
            baseBindingVersion: b?.version,
          },
          { credential: p.credential },
        );
      }
      known[p.nativeConnectionId] = p.snapshot;
    }
    const live = new Set(rows.map((p) => p.nativeConnectionId)),
      removed = Object.keys(known).filter((k) => !live.has(k));
    if (removed.length) {
      this.enqueue("inventory", { profiles: [], removedIds: removed });
      for (const k of removed) delete known[k];
    }
    this.save();
    void this.flush();
  }
  async request(route, body, connector = false) {
    const c = this.s.config;
    if (!c) throw new Error("尚未配对资源中心");
    const response = await fetch(`${c.url.replace(/\/$/, "")}${route}`, {
      method: body === undefined ? "GET" : "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${connector ? c.connectorToken : c.rpToken}`,
      },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
      signal: AbortSignal.timeout(12000),
    });
    const result = await response.json();
    if (!response.ok)
      throw Object.assign(new Error(`中心请求未完成（HTTP ${response.status}）`), {
        status: response.status,
      });
    return result;
  }
  remember(b) {
    this.s.mappings[b.nativeConnectionId] = b;
  }
  async flush() {
    if (this.busy || !this.s.config) return;
    this.busy = true;
    try {
      const batch = [...this.s.queue];
      for (const q of batch) {
        const nativeId =
          q.body.nativeConnectionId || (q.kind === "legacy-save" ? q.body.profileId : undefined);
        if (nativeId && this.s.problems[nativeId]?.connection) continue;
        try {
          let result;
          if (q.kind === "inventory") {
            result = await this.request("/api/v2/rp/inventory", { eventId: q.eventId, ...q.body });
            for (const b of result.items) {
              if (b.id) {
                this.remember(b);
                const credential = q.credentials?.[b.nativeConnectionId];
                if (
                  credential &&
                  b.credentialFingerprint !== this.s.observed[b.nativeConnectionId]?.credentialFingerprint &&
                  !b.conflict
                )
                  this.enqueue("credential", {
                    nativeConnectionId: b.nativeConnectionId,
                    baseChannelVersion: b.channelVersion,
                    baseBindingVersion: b.version,
                    credential,
                  });
              } else this.s.problems[b.nativeConnectionId] = { error: b.error };
            }
            this.s.registered = true;
          } else if (q.kind === "receipt") {
            try {
              result = await this.request("/api/v2/connector/receipts", q.body, true);
            } catch (e) {
              if (e.status !== 409) throw e;
              result = { staleLease: true };
            }
          } else {
            const b = this.s.mappings[nativeId];
            if (!b) continue;
            if (q.kind === "legacy-save") {
              const snapshot = this.s.observed[nativeId],
                old = q.body;
              if (!snapshot || (old.channelId && old.channelId !== b.channelId)) {
                this.s.problems[nativeId] = { error: "旧保存记录的连接关联待确认，原记录已保留" };
                continue;
              }
              q.kind = "save";
              q.body = {
                nativeConnectionId: nativeId,
                localRevision: ++this.s.localRevision,
                baseChannelVersion: old.expectedVersion,
                baseBindingVersion: b.version,
                snapshot: {
                  ...snapshot,
                  ...Object.fromEntries(
                    ["name", "baseUrl", "protocol", "order", "enabled"]
                      .filter((k) => old.patch[k] !== undefined)
                      .map((k) => [k, old.patch[k]]),
                  ),
                  selectedModel: old.patch.models?.[0] || snapshot.selectedModel,
                },
              };
              this.save();
            }
            const body = {
              ...q.body,
              eventId: q.eventId,
              baseChannelVersion: q.body.baseChannelVersion || b.channelVersion,
              baseBindingVersion: q.body.baseBindingVersion || b.version,
            };
            result = await this.request(
              q.kind === "save" ? "/api/v2/rp/saves" : "/api/v2/rp/credentials",
              body,
            );
            if (result.connection) this.remember(result.connection);
            if (result.state === "conflict")
              this.s.problems[nativeId] = { connection: result.connection, event: q };
            else {
              const accepted = result.connection;
              // Rebase only successive edits from our own accepted local lineage.
              for (const later of this.s.queue)
                if (
                  later !== q &&
                  later.body.nativeConnectionId === nativeId &&
                  later.body.baseBindingVersion === q.body.baseBindingVersion &&
                  later.body.baseChannelVersion === q.body.baseChannelVersion
                ) {
                  later.body.baseChannelVersion = accepted.channelVersion;
                  later.body.baseBindingVersion = accepted.version;
                }
              if (
                q.kind === "save" &&
                q.credential &&
                accepted.credentialFingerprint !== q.body.snapshot.credentialFingerprint
              )
                this.s.queue.splice(this.s.queue.indexOf(q) + 1, 0, {
                  kind: "credential",
                  eventId: randomUUID(),
                  body: {
                    nativeConnectionId: nativeId,
                    baseChannelVersion: accepted.channelVersion,
                    baseBindingVersion: accepted.version,
                    credential: q.credential,
                  },
                });
            }
          }
          this.s.queue = this.s.queue.filter((x) => x.eventId !== q.eventId);
          this.s.lastAck = new Date().toISOString();
          delete this.s.error;
          this.save();
          for (const extra of this.s.queue) if (!batch.includes(extra)) batch.push(extra);
        } catch (e) {
          if (e.status === 400 || e.status === 403 || e.status === 409) {
            this.s.problems[nativeId || q.eventId] = { error: cleanError(e) };
            continue;
          }
          throw e;
        }
      }
      for (const [id, row] of Object.entries(this.s.calls)) {
        if (row.acknowledged) continue;
        const revision = row.revision;
        const result = await this.request("/api/v2/ingest/rp-calls", { events: [row.event] });
        if (result.acknowledgedIds?.includes(id) && this.s.calls[id]?.revision === revision) {
          if (row.event.result === "pending") row.acknowledged = true;
          else delete this.s.calls[id];
          this.save();
        }
      }
    } catch (e) {
      this.s.error = cleanError(e);
      this.save();
    } finally {
      this.busy = false;
    }
  }
  async refresh() {
    const result = await this.request("/api/v2/rp/connections");
    for (const b of result.items) {
      const previous = this.s.mappings[b.nativeConnectionId];
      if (
        previous?.conflict?.reason === "首次接入的共享配置或凭据与中心不同" &&
        !b.conflict &&
        !b.credentialFingerprint
      ) {
        const native = this.native().rows.find((p) => p.nativeConnectionId === b.nativeConnectionId);
        if (
          native?.credential &&
          native.snapshot?.protocol === b.protocol &&
          canonical(native.snapshot.baseUrl, b.protocol) === canonical(b.baseUrl, b.protocol)
        )
          this.enqueue("credential", {
            nativeConnectionId: b.nativeConnectionId,
            baseChannelVersion: b.channelVersion,
            baseBindingVersion: b.version,
            credential: native.credential,
          });
      }
      const problem = this.s.problems[b.nativeConnectionId];
      if (problem?.connection && !b.conflict) {
        delete this.s.problems[b.nativeConnectionId];
        if (b.lastResolution === "local") {
          const credential =
            problem.event?.credential ||
            this.native().rows.find((p) => p.nativeConnectionId === b.nativeConnectionId)?.credential;
          if (credential)
            this.enqueue("credential", {
              nativeConnectionId: b.nativeConnectionId,
              baseChannelVersion: b.channelVersion,
              baseBindingVersion: b.version,
              credential,
            });
        }
      }
      this.remember(b);
    }
    this.save();
    return result.items;
  }
  status() {
    return {
      version: "2.0.0",
      configured: !!this.s.config,
      url: this.s.config?.url || "",
      instanceId: this.s.config?.instanceId || "",
      user: this.user,
      connections: Object.values(this.s.mappings),
      problems: Object.fromEntries(
        Object.entries(this.s.problems).map(([k, v]) => [k, { error: v.error, connection: v.connection }]),
      ),
      queue: this.s.queue.length,
      inventoryTotal: Object.keys(this.s.observed).length,
      calls: Object.keys(this.s.calls).length,
      error: this.s.error || "",
      lastAck: this.s.lastAck || null,
      active: this.active,
      selected: readSettings(this.dirs).extension_settings?.connectionManager?.selectedProfile || null,
      coverage: this.s.coverage || null,
    };
  }
  async poll(page) {
    this.observe();
    await this.flush();
    await this.refresh();
    await this.flush();
    const active = this.page && this.page !== page && Date.now() < this.pageUntil;
    if (active) return { ...this.status(), jobs: [], leader: false };
    this.page = page;
    this.pageUntil = Date.now() + 45000;
    if (this.active) return { ...this.status(), jobs: [], leader: true };
    const result = await this.request("/api/v2/connector/jobs", undefined, true);
    // A receipt lost after native save must be replayable under a newly issued lease.
    this.jobs = new Map(result.items.map((j) => [j.id, j]));
    return {
      ...this.status(),
      jobs: result.items.map((j) => ({ ...j, payload: { ...j.payload, credential: undefined } })),
      leader: true,
    };
  }
  async prepare(page, id) {
    if (this.page !== page || Date.now() > this.pageUntil)
      throw Object.assign(new Error("配置应用由另一个标签页处理"), { status: 409 });
    const job = this.jobs?.get(id);
    if (!job) throw Object.assign(new Error("任务已过期，请重新同步"), { status: 409 });
    const { settings, rows } = this.native(),
      p = rows.find((p) => p.nativeConnectionId === job.payload.nativeConnectionId);
    if (!p?.snapshot) throw new Error("原生连接尚未解析");
    if (this.active) {
      this.enqueue("receipt", {
        id: job.id,
        lease: job.lease,
        state: "waiting",
        reason: "正在生成，配置稍后应用",
      });
      await this.flush();
      throw new Error("正在生成，配置稍后应用");
    }
    if (
      job.expected &&
      !same(p.snapshot, job.expected) &&
      !same(p.snapshot, Object.fromEntries(Object.keys(p.snapshot).map((k) => [k, job.payload[k]])))
    ) {
      this.enqueue("receipt", {
        id: job.id,
        lease: job.lease,
        state: "conflict",
        snapshot: p.snapshot,
        reason: "酒馆已保存配置与中心基线不同",
      });
      await this.flush();
      throw new Error("连接配置冲突，请选择采用哪一侧");
    }
    const profile = settings.extension_settings.connectionManager.profiles.find(
      (x) => x.id === p.nativeConnectionId,
    );
    const patch = nativePatch(settings, profile, job.payload, this.manager(), this.s.prepared?.patch);
    const snapshot = Object.fromEntries(Object.keys(p.snapshot).map((k) => [k, job.payload[k]]));
    this.s.prepared = { job, patch, nativeConnectionId: p.nativeConnectionId, snapshot };
    this.save();
    return {
      id: job.id,
      profile: patch.profile,
      proxies: patch.proxies,
      snapshot,
      remote: { ...job.payload, credential: undefined },
      selected: settings.extension_settings.connectionManager.selectedProfile,
    };
  }
  applied(id) {
    if (this.s.completed?.[id]) return { saved: true };
    if (this.s.prepared?.job.id !== id) {
      if (this.s.queue.some((q) => q.kind === "receipt" && q.body.id === id)) return { saved: true };
      throw new Error("未找到待确认的原生保存");
    }
    this.observe();
    if (this.s.prepared?.job.id === id) throw new Error("原生回读尚未匹配，保存未确认");
    void this.flush();
    return { saved: true };
  }
  report(event) {
    const old = this.s.calls[event.eventId];
    this.s.calls[event.eventId] = { event, revision: (old?.revision || 0) + 1, acknowledged: false };
    this.save();
    void this.flush();
  }
}
function session(req) {
  if (!req.user) throw Object.assign(new Error("请先登录酒馆"), { status: 401 });
  const user = req.user.profile.handle;
  if (!sessions.has(user)) sessions.set(user, new Session(req.user.directories, user));
  return sessions.get(user);
}
export async function init(router) {
  const load = (p) => import(pathToFileURL(path.join(serverRoot(), p)).href);
  const [secrets, settings, chat, users, util] = await Promise.all([
    load("src/endpoints/secrets.js"),
    load("src/endpoints/settings.js"),
    load("src/endpoints/backends/chat-completions.js"),
    load("src/users.js"),
    load("src/util.js"),
  ]);
  host = { secrets, users };
  const route = (fn) => async (req, res) => {
    try {
      res.setHeader("Cache-Control", "no-store");
      res.json(await fn(session(req), req.body || {}, req));
    } catch (e) {
      res.status(e.status || 400).json({ error: cleanError(e) });
    }
  };
  router.get(
    "/status",
    route((s) => s.status()),
  );
  router.post(
    "/configure",
    route(async (s, b) => {
      const u = new URL(b.url);
      if (!["http:", "https:"].includes(u.protocol) || u.username || u.password)
        throw new Error("资源中心地址无效");
      if (!b.rpToken || !b.connectorToken || !b.instanceId) throw new Error("需要实例 ID 和两种受限凭据");
      if (s.s.config && s.s.config.url !== u.href.replace(/\/$/, ""))
        throw new Error("切换中心前请先处理已有待发队列");
      const before = s.s.config;
      s.s.config = {
        url: u.href.replace(/\/$/, ""),
        rpToken: b.rpToken,
        connectorToken: b.connectorToken,
        instanceId: b.instanceId,
      };
      try {
        const identity = await s.request("/api/v2/rp/identity");
        const connector = await s.request("/api/v2/rp/identity", undefined, true);
        if (identity.instanceId !== b.instanceId || identity.userId !== s.user || !same(identity, connector))
          throw new Error("配对凭据的实例或酒馆用户不匹配");
      } catch (e) {
        s.s.config = before;
        throw e;
      }
      s.save();
      await s.refresh();
      s.observe();
      await s.flush();
      return s.status();
    }),
  );
  router.post(
    "/poll",
    route((s, b) => {
      if (typeof b.page !== "string" || b.page.length > 160) throw new Error("缺少标签页标识");
      return s.poll(b.page);
    }),
  );
  router.post(
    "/prepare",
    route((s, b) => s.prepare(b.page, b.id)),
  );
  router.post(
    "/applied",
    route((s, b) => s.applied(b.id)),
  );
  router.post(
    "/cancel",
    route((s, b) => {
      if (typeof b.eventId !== "string" || b.eventId.length > 160) throw new Error("请求 ID 无效");
      s.cancelled ??= new Set();
      s.cancelled.add(b.eventId);
      s.finalizers?.get(b.eventId)?.finish(false);
      setTimeout(() => s.cancelled?.delete(b.eventId), 60000).unref();
      return { recorded: true };
    }),
  );
  router.post(
    "/archive",
    route(async (s, b) => {
      if (
        readSettings(s.dirs).extension_settings?.connectionManager?.selectedProfile === b.nativeConnectionId
      )
        throw new Error("当前连接不能归档，请先选择其他连接");
      const c = s.s.mappings[b.nativeConnectionId];
      if (!c) throw new Error("连接尚未完成关联");
      const result = await s.request("/api/v2/rp/archive", {
        nativeConnectionId: b.nativeConnectionId,
        channelVersion: c.channelVersion,
        reason: b.reason,
        note: b.note || "",
      });
      s.remember(result);
      s.save();
      return result;
    }),
  );
  router.post(
    "/resolve",
    route(async (s, b) => {
      const c = s.s.mappings[b.nativeConnectionId];
      if (!c) throw new Error("连接尚未完成关联");
      const problem = s.s.problems[b.nativeConnectionId];
      const result = await s.request("/api/v2/rp/resolve", {
        nativeConnectionId: b.nativeConnectionId,
        version: c.version,
        channelVersion: c.channelVersion,
        resolve: b.resolve,
        binding: b.binding || {},
        channel: b.channel || {},
      });
      s.remember(result);
      delete s.s.problems[b.nativeConnectionId];
      s.save();
      if (b.resolve === "local" || b.credentialSide === "local") {
        const credential =
          problem?.event?.credential ||
          s.native().rows.find((p) => p.nativeConnectionId === b.nativeConnectionId)?.credential;
        if (credential)
          s.enqueue("credential", {
            nativeConnectionId: b.nativeConnectionId,
            baseChannelVersion: result.channelVersion,
            baseBindingVersion: result.version,
            credential,
          });
      }
      await s.flush();
      return s.status();
    }),
  );
  router.post(
    "/legacy",
    route(async (s, b) => {
      if (!Array.isArray(b.entries) || b.entries.length > 2000) throw new Error("旧队列格式无效");
      // Preserve old device / event identity and use the old scope only for draining old records.
      const settings = readSettings(s.dirs).extension_settings?.aiResourceCenter;
      if (!settings?.token) return { acknowledgedIds: [] };
      const acknowledgedIds = [];
      for (const row of b.entries) {
        if (!row?.event?.eventId) continue;
        const response = await fetch(`${s.s.config.url}/api/v1/rp/calls`, {
          method: "POST",
          headers: { "Content-Type": "application/json", Authorization: `Bearer ${settings.token}` },
          body: JSON.stringify({ device: row.device, events: [row.event] }),
          signal: AbortSignal.timeout(12000),
        });
        if (!response.ok) throw new Error("旧调用队列待重交");
        const result = await response.json();
        acknowledgedIds.push(...result.acknowledgedIds);
      }
      return { acknowledgedIds };
    }),
  );
  attach(settings.router, (req, res, next) => {
    if (req.path === "/save" && req.user)
      res.once("finish", () => {
        if (res.statusCode >= 200 && res.statusCode < 300) {
          try {
            session(req).observe();
          } catch {
            const s = session(req);
            s.s.coverage = "原生保存后未能采集连接快照";
            s.save();
          }
        }
      });
    next();
  });
  attach(chat.router, (req, res, next) => {
    if (req.path !== "/generate" || req.headers["x-arc-client"] !== "2" || !req.user) return next();
    const s = session(req);
    if (!s.s.config) return next();
    let facts;
    try {
      facts = requestFacts(req.body, s.manager(), util);
    } catch {
      s.s.coverage = "本次请求协议尚未采集，未推测调用归属";
      s.save();
      return next();
    }
    const rawId = String(req.headers["x-arc-request-id"] || ""),
      eventId = /^[\w-]{16,160}$/.test(rawId) ? rawId : randomUUID();
    const profileId = String(req.headers["x-arc-profile-id"] || "");
    const event = {
      eventId,
      ...facts,
      ...(profileId ? { profileId } : {}),
      origin: "live",
      occurredAt: new Date().toISOString(),
      isStream: !!req.body.stream,
      result: "pending",
    };
    const started = performance.now(),
      parser = new ResponseFacts(started);
    const socket = res.socket;
    let ended = false;
    s.active++;
    try {
      s.report(event);
    } catch {
      s.s.coverage = "本次请求开始未能写入采集队列";
    }
    const write = res.write,
      end = res.end;
    const feed = (chunk) => {
      if (chunk != null)
        try {
          parser.feed(chunk, event.isStream);
        } catch {
          /* metadata failure never changes the generation */
        }
    };
    res.write = function (chunk, ...args) {
      feed(chunk);
      return Reflect.apply(write, this, [chunk, ...args]);
    };
    res.end = function (chunk, ...args) {
      feed(chunk);
      return Reflect.apply(end, this, [chunk, ...args]);
    };
    function finish(closed) {
      if (ended) return;
      ended = true;
      s.finalizers?.delete(eventId);
      s.active--;
      const extra = parser.end(event.isStream),
        statusCode = res.statusCode;
      const cancelled = s.cancelled?.has(eventId);
      s.cancelled?.delete(eventId);
      const result =
        cancelled && !parser.terminal
          ? "cancelled"
          : statusCode >= 400 || parser.error
            ? "failure"
            : parser.terminal
              ? "success"
              : cancelled
                ? "cancelled"
                : "unknown";
      const errorType =
        parser.errorType ||
        (statusCode === 401 || statusCode === 403
          ? "key"
          : statusCode === 429
            ? "rate"
            : statusCode >= 500
              ? "upstream"
              : statusCode >= 400
                ? "input"
                : result === "cancelled"
                  ? "cancelled"
                  : undefined);
      try {
        s.report({
          ...event,
          ...extra,
          statusCode,
          result,
          latency: performance.now() - started,
          ...(errorType ? { errorType } : {}),
          ...(event.isStream
            ? {
                streamStatus:
                  result === "success"
                    ? "completed"
                    : result === "cancelled"
                      ? "cancelled"
                      : closed || !parser.terminal
                        ? "disconnected"
                        : result === "failure"
                          ? "failed"
                          : "unknown",
              }
            : {}),
        });
      } catch {
        s.s.coverage = "本次调用终态未能写入队列";
      }
    }
    res.once("finish", () => {
      if (!parser.terminal && res.statusCode < 400 && !parser.error) setTimeout(() => finish(false), 150);
      else finish(false);
    });
    res.once("close", () => {
      if (!res.writableFinished || !parser.terminal) setTimeout(() => finish(!res.writableFinished), 150);
      else finish(false);
    });
    // Native forwarding may leave its downstream response open when the upstream stream fails.
    // Watching the piped source adds no reader and does not change stream flow or backpressure.
    res.once("pipe", (source) => {
      source.once("error", () => {
        parser.error = true;
        parser.errorType = "upstream";
        setTimeout(() => finish(true), 150);
      });
      source.once("close", () => {
        if (!source.readableEnded) setTimeout(() => finish(true), 150);
      });
    });
    s.finalizers ??= new Map();
    s.finalizers.set(eventId, {
      finish,
      ended: () => res.writableFinished || res.destroyed || socket?.destroyed,
    });
    next();
  });
  for (const user of await users.getAllUserHandles()) {
    const dirs = users.getUserDirectories(user);
    if (fs.existsSync(path.join(dirs.root, "resource-center-link", "state.enc")))
      sessions.set(user, new Session(dirs, user));
  }
  let tick = 0;
  timer = setInterval(() => {
    tick++;
    for (const s of sessions.values()) {
      for (const f of s.finalizers?.values() || []) if (f.ended()) f.finish(true);
      if (tick % 30 === 0) void s.flush();
    }
  }, 1000);
  timer.unref();
  console.log("resource-center-link: native save and generation observers ready");
}
export async function exit() {
  clearInterval(timer);
  for (const fn of detach.splice(0)) fn();
  for (const s of sessions.values()) if (s.s.config) s.save();
  sessions.clear();
}
