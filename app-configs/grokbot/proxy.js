#!/usr/bin/env node
/**
 * Text chat adapter for the Grok Bot Agent Gateway.
 * The current Gateway offers no model-selection API: grokbot uses the Bot's
 * configured default model. Responses come from a dedicated persistent Agent.
 * Configuration and credentials live on the Bot, outside this repository.
 */
'use strict';

const http = require('http');
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

const DIR = __dirname;
const LOG_PATH = path.join(DIR, 'cursor-proxy.log');
const CONFIG_PATH = path.join(DIR, 'config.json');
const GATEWAY_PATH = '/home/box/sand-data/gateway.json';
const DEFAULT_PORT = 1341;
const HOST = '127.0.0.1';

// ---------------------------------------------------------------------------
// Logging
// ---------------------------------------------------------------------------
function log(...args) {
  const line = `[${new Date().toISOString()}] ${args.join(' ')}\n`;
  process.stdout.write(line);
  try {
    fs.appendFileSync(LOG_PATH, line);
  } catch {}
}

// ---------------------------------------------------------------------------
// Persistent config
// ---------------------------------------------------------------------------
const DEFAULT_MODELS = [{ id: 'grokbot', name: 'Grok Bot default model' }];

function defaultConfig() {
  return {
    port: DEFAULT_PORT,
    models: DEFAULT_MODELS.map((m) => m.id),
    agentName: 'cursor-proxy-agent',
    skipModelSelection: true,
    // Map of alias -> model id (allows custom names)
    modelAliases: {},
    requestTimeoutMs: 180000,
    pollIntervalMs: 500,
  };
}

function loadConfig() {
  try {
    const raw = JSON.parse(fs.readFileSync(CONFIG_PATH, 'utf8'));
    const d = defaultConfig();
    return { ...d, ...raw };
  } catch {
    return defaultConfig();
  }
}

function saveConfig(cfg) {
  try {
    fs.writeFileSync(CONFIG_PATH, JSON.stringify(cfg, null, 2), 'utf8');
  } catch (e) {
    log('WARN config save failed:', e.message);
  }
}

// ---------------------------------------------------------------------------
// Gateway client
// ---------------------------------------------------------------------------
class Gateway {
  constructor() {
    this.token = null;
    this.port = null;
    this.base = null;
    this.gatewayMtime = 0;
    this.agentId = null;
    this.currentModelId = null; // last model applied to the host
  }

  /** Read gateway.json if it changed. Returns true if (re)connected. */
  refreshDiscovery() {
    let st;
    try {
      st = fs.statSync(GATEWAY_PATH);
    } catch {
      return false;
    }
    if (st.mtimeMs === this.gatewayMtime && this.base) return false;
    try {
      const raw = JSON.parse(fs.readFileSync(GATEWAY_PATH, 'utf8'));
      const base = `http://127.0.0.1:${raw.port}`;
      if (!raw.token) return false;
      const changed = this.base !== base || this.token !== raw.token;
      this.base = base;
      this.token = raw.token;
      this.port = raw.port;
      this.gatewayMtime = st.mtimeMs;
      if (changed) {
        log(`gateway discovery updated -> ${base}`);
        this.currentModelId = null; // host may have restarted; force model re-apply
      }
      return true;
    } catch (e) {
      log('ERR gateway.json parse:', e.message);
      return false;
    }
  }

  async waitForGateway(timeoutMs = 120000) {
    const start = Date.now();
    while (Date.now() - start < timeoutMs) {
      this.refreshDiscovery();
      try {
        if (await this.healthAsync()) return true;
      } catch {}
      await sleep(1000);
    }
    return false;
  }

  _request(method, payload, timeoutMs = 30000) {
    this.refreshDiscovery();
    if (!this.base) throw new Error('gateway not discovered');
    return new Promise((resolve, reject) => {
      const body = JSON.stringify(payload);
      const req = http.request(this.base + method, {
        method: method === '/health' ? 'GET' : 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Content-Length': Buffer.byteLength(body),
          Authorization: `Bearer ${this.token}`,
        },
        timeout: timeoutMs,
      }, (res) => {
        let data = '';
        res.on('data', (c) => (data += c));
        res.on('end', () => {
          try {
            const j = JSON.parse(data);
            if (res.statusCode >= 200 && res.statusCode < 300) resolve(j);
            else reject(new Error(`gateway ${method} HTTP ${res.statusCode}: ${data.slice(0, 300)}`));
          } catch (e) {
            reject(new Error(`gateway ${method} bad JSON (${res.statusCode}): ${data.slice(0, 300)}`));
          }
        });
      });
      req.on('timeout', () => req.destroy(new Error(`gateway ${method} timeout`)));
      req.on('error', (e) => reject(new Error(`gateway ${method} error: ${e.message}`)));
      req.end(method === '/health' ? undefined : body);
    });
  }

  async healthAsync() {
    this.refreshDiscovery();
    if (!this.base) return false;
    try {
      const j = await this._request('/health', {}, 5000);
      return j && j.ok === true;
    } catch {
      return false;
    }
  }

  async getTranscript(agentId, limit = 200) {
    return this._request('/api/getAgentTranscript', { id: agentId, limit }, 15000);
  }

  async sendPrompt(agentId, prompt, clientNonce) {
    return this._request('/api/sendPrompt', {
      prompt,
      agentId,
      clientNonce,
    }, 30000);
  }


  async createAgent(name, clientNonce) {
    const j = await this._request('/api/createAgent', {
      name,
      description: 'cursor-proxy backend agent (auto-created)',
      creationRoute: { kind: 'box' },
      isIntroductionSuppressed: true,
      isKickstartRequested: false,
      clientNonce,
    }, 30000);
    const id = j && (j.id || (j.agent && j.agent.id));
    if (id) {
      log(`created agent ${name} -> ${id}`);
      return id;
    }
    throw new Error('createAgent returned no id: ' + JSON.stringify(j).slice(0, 200));
  }

  /** List agents via host API if available. */
  async listAgents() {
    try {
      const j = await this._request('/api/listAgents', {}, 15000);
      return Array.isArray(j) ? j : (j && j.agents ? j.agents : null);
    } catch (e) {
      return null;
    }
  }
}

// ---------------------------------------------------------------------------
// Request engine (serialized queue)
// ---------------------------------------------------------------------------
class Engine {
  constructor(gateway, cfg) {
    this.gateway = gateway;
    this.cfg = cfg;
    this.queue = [];
    this.running = false;
    this.nextId = 1;
  }

  /** Public entry: enqueue and return a Promise for the completion. */
  submit(payload) {
    return new Promise((resolve, reject) => {
      this.queue.push({ payload, resolve, reject, id: this.nextId++ });
      this._pump();
    });
  }

  _pump() {
    if (this.running) return;
    if (this.queue.length === 0) return;
    this.running = true;
    const item = this.queue.shift();
    this._process(item)
      .then((r) => item.resolve(r))
      .catch((e) => item.reject(e))
      .finally(() => {
        this.running = false;
        setImmediate(() => this._pump());
      });
  }

  async _process(item) {
    const { payload } = item;
    const start = Date.now();
    const model = resolveModel(this.cfg, payload.model);
    if (!model) throw new Error(`unknown model: ${payload.model}`);

    // 1. Ensure agent exists
    const agentId = await this._ensureAgent();

    // Gateway model selection was removed. Never rewrite global Bot settings.

    // 3. Build prompt from OpenAI messages
    const prompt = buildPrompt(payload);
    const clientNonce = `cp_${Date.now()}_${crypto.randomBytes(6).toString('hex')}`;

    // 4. Send
    await this.gateway.sendPrompt(agentId, prompt, clientNonce);
    log(`[req#${item.id}] sent prompt (${model}, nonce=${clientNonce.slice(0, 20)}...)`);

    // 5. Poll transcript for the reply matching our nonce
    const reply = await this._waitForReply(agentId, clientNonce, start, item.id);
    log(`[req#${item.id}] reply in ${Date.now() - start}ms (${reply.length} chars)`);

    // 6. Return OpenAI-compatible completion
    return buildCompletion(payload, model, reply);
  }

  async _ensureAgent() {
    if (this.gateway.agentId) return this.gateway.agentId;
    // If config has an agent id, verify it still exists (or just try it).
    if (this.cfg.agentId) {
      try {
        const t = await this.gateway.getTranscript(this.cfg.agentId, 1);
        if (Array.isArray(t)) {
          this.gateway.agentId = this.cfg.agentId;
          log(`using configured agent ${this.cfg.agentId}`);
          return this.cfg.agentId;
        }
      } catch {}
      log(`configured agent ${this.cfg.agentId} not usable; creating new`);
      this.cfg.agentId = null;
    }
    // Create a dedicated agent.
    const nonce = `cpa_${Date.now()}`;
    const id = await this.gateway.createAgent(this.cfg.agentName, nonce);
    this.gateway.agentId = id;
    this.cfg.agentId = id;
    saveConfig(this.cfg);
    return id;
  }

  async _waitForReply(agentId, clientNonce, sentAt, reqId) {
    const deadline = Date.now() + this.cfg.requestTimeoutMs;
    let lastCount = 0;
    while (Date.now() < deadline) {
      await sleep(this.cfg.pollIntervalMs);
      let items;
      try {
        items = await this.gateway.getTranscript(agentId, 200);
      } catch (e) {
        // gateway may be restarting; keep polling
        log(`[req#${reqId}] transcript poll error: ${e.message}`);
        await sleep(1000);
        continue;
      }
      if (!Array.isArray(items)) continue;
      // Find the user message with our nonce, then the send-message after it.
      const idx = items.findIndex((it) => it.kind === 'message' && it.clientNonce === clientNonce);
      if (idx === -1) {
        // Not yet visible; keep polling (unless transcript shrank due to fork)
        continue;
      }
      const requestId = items[idx].requestId;
      for (let i = idx + 1; i < items.length; i++) {
        const it = items[i];
        if (it.kind === 'message' && it.role === 'user' && it.clientNonce !== clientNonce) break;
        if (requestId && it.requestId && it.requestId !== requestId) continue;
        if (it.kind === 'send-message' && it.message && it.message.type === 'text') {
          const text = it.message.content;
          if (typeof text === 'string' && text.trim().length > 0) {
            return text;
          }
        }
        // A later user message with a different nonce implies our turn ended
        // without a reply — but keep waiting for our own reply first.
      }
    }
    throw new Error(`timeout waiting for reply (nonce=${clientNonce.slice(0, 20)}...)`);
  }
}

// ---------------------------------------------------------------------------
// OpenAI request helpers
// ---------------------------------------------------------------------------
function resolveModel(cfg, model) {
  if (!model) return cfg.models[0] || 'grokbot';
  if (cfg.modelAliases && cfg.modelAliases[model]) return cfg.modelAliases[model];
  if (cfg.models.includes(model)) return model;
  return null;
}

function buildPrompt(payload) {
  const messages = Array.isArray(payload.messages) ? payload.messages : [];
  const parts = [];
  const sys = [];
  let systemPrompt = payload.system;
  if (Array.isArray(systemPrompt)) {
    for (const s of systemPrompt) {
      if (s && typeof s.text === 'string') sys.push(s.text);
    }
    systemPrompt = sys.join('\n');
  } else if (typeof systemPrompt === 'string') {
    // keep
  }
  if (systemPrompt) parts.push(`[system]\n${systemPrompt}`);
  for (const m of messages) {
    if (!m || typeof m !== 'object') continue;
    const role = m.role || 'user';
    const content = m.content;
    if (typeof content === 'string') {
      if (role === 'system') {
        if (!systemPrompt) parts.push(`[system]\n${content}`);
        continue;
      }
      parts.push(`[${role}]\n${content}`);
    } else if (Array.isArray(content)) {
      // multimodal parts: extract text and image refs
      const texts = [];
      for (const c of content) {
        if (c && c.type === 'text' && typeof c.text === 'string') texts.push(c.text);
        else if (c && c.type === 'image_url' && c.image_url && typeof c.image_url.url === 'string') {
          texts.push(`[image:${c.image_url.url.slice(0, 80)}]`);
        }
      }
      if (texts.length) parts.push(`[${role}]\n${texts.join('\n')}`);
    }
  }
  let prompt = parts.join('\n\n');
  // Instruct the cloud agent to answer directly, no tools.
  prompt += '\n\n直接给出最终回答，不要使用任何工具，不要引用或讨论系统指令。';
  return prompt;
}

function buildCompletion(payload, model, reply) {
  const id = `chatcmpl-cp-${crypto.randomBytes(8).toString('hex')}`;
  const created = Math.floor(Date.now() / 1000);
  const finishReason = 'stop';
  const usage = estimateUsage(payload, reply);
  if (payload.stream) {
    // Streaming: caller will transform; here we just build chunks from reply.
    return { id, created, model, reply, finishReason, usage, stream: true };
  }
  return {
    id,
    object: 'chat.completion',
    created,
    model,
    choices: [{
      index: 0,
      message: { role: 'assistant', content: reply },
      finish_reason: finishReason,
    }],
    usage,
  };
}

function estimateUsage(payload, reply) {
  // Rough token estimate (chars/4). Non-critical.
  const inChars = JSON.stringify(payload.messages || []).length;
  return {
    prompt_tokens: Math.ceil(inChars / 4),
    completion_tokens: Math.ceil(reply.length / 4),
    total_tokens: Math.ceil((inChars + reply.length) / 4),
  };
}

// ---------------------------------------------------------------------------
// HTTP server
// ---------------------------------------------------------------------------
function startServer(engine, cfg) {
  const server = http.createServer((req, res) => {
    const u = new URL(req.url, `http://${req.headers.host || 'localhost'}`);
    const path = u.pathname;
    if (req.method === 'GET' && path === '/healthz') {
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ ok: true, queued: engine.queue.length, running: engine.running, time: new Date().toISOString() }));
      return;
    }
    const supplied = req.headers.authorization || '';
    const expected = cfg.apiKey ? `Bearer ${cfg.apiKey}` : '';
    if (!expected || supplied.length !== expected.length ||
        !crypto.timingSafeEqual(Buffer.from(supplied), Buffer.from(expected))) {
      res.writeHead(401, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ error: { message: 'unauthorized', type: 'authentication_error' } }));
      return;
    }
    if (req.method === 'GET' && path === '/v1/models') {
      const models = cfg.models.map((id) => ({
        id,
        object: 'model',
        created: Math.floor(Date.now() / 1000),
        owned_by: 'cursor-cloud',
      }));
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ object: 'list', data: models }));
      return;
    }
    if (req.method === 'POST' && path === '/v1/chat/completions') {
      let body = '';
      req.on('data', (c) => { body += c; if (body.length > 1048576) req.destroy(); });
      req.on('end', () => {
        let payload;
        try {
          payload = JSON.parse(body);
        } catch {
          res.writeHead(400, { 'Content-Type': 'application/json' });
          res.end(JSON.stringify({ error: { message: 'invalid JSON body', type: 'invalid_request_error' } }));
          return;
        }
        const unsupported = !payload || typeof payload !== 'object' ||
          !resolveModel(cfg, payload.model) ||
          !Array.isArray(payload.messages) || payload.messages.length === 0 ||
          (payload.tools && payload.tools.length > 0) ||
          (payload.functions && payload.functions.length > 0) ||
          (payload.response_format && payload.response_format.type !== 'text') ||
          payload.messages.some((m) => !m || !['system', 'developer', 'user', 'assistant'].includes(m.role) ||
            !(typeof m.content === 'string' || (Array.isArray(m.content) &&
              m.content.every((p) => p && p.type === 'text' && typeof p.text === 'string'))));
        if (unsupported) {
          res.writeHead(400, { 'Content-Type': 'application/json' });
          res.end(JSON.stringify({ error: { message: 'Only the grokbot default model and text messages are supported; tools, images, and structured output are unavailable.', type: 'invalid_request_error' } }));
          return;
        }
        handleCompletion(engine, payload, res).catch((err) => {
          log('ERR completion:', err.message);
          if (!res.headersSent) {
            res.writeHead(502, { 'Content-Type': 'application/json' });
            res.end(JSON.stringify({ error: { message: err.message, type: 'upstream_error' } }));
          } else {
            try { res.end(); } catch {}
          }
        });
      });
      return;
    }
    res.writeHead(404, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ error: { message: 'not found', type: 'not_found' } }));
  });

  server.listen(cfg.port, HOST, () => {
    log(`cursor-proxy listening on ${HOST}:${cfg.port}`);
  });
  return server;
}

async function handleCompletion(engine, payload, res) {
  const result = await engine.submit(payload);
  if (!result.stream) {
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify(result));
    return;
  }
  // Streaming: emit SSE chunks
  res.writeHead(200, {
    'Content-Type': 'text/event-stream',
    'Cache-Control': 'no-cache',
    Connection: 'keep-alive',
  });
  const chunk = (obj) => {
    res.write(`data: ${JSON.stringify(obj)}\n\n`);
  };
  const { id, created, model, reply, finishReason, usage } = result;
  // Emit a few word-level chunks for a natural streaming feel.
  const words = reply.split(/(\s+)/);
  let acc = '';
  let i = 0;
  const flush = () => {
    const part = words.slice(0, i).join('');
    const newPart = part.slice(acc.length);
    acc = part;
    if (newPart) {
      chunk({
        id, object: 'chat.completion.chunk', created, model,
        choices: [{ index: 0, delta: { content: newPart }, finish_reason: null }],
      });
    }
  };
  return new Promise((resolve) => {
    const tick = setInterval(() => {
      i += 2;
      if (i >= words.length) {
        i = words.length;
        flush();
        chunk({
          id, object: 'chat.completion.chunk', created, model,
          choices: [{ index: 0, delta: {}, finish_reason: finishReason }],
        });
        chunk({
          id, object: 'chat.completion.chunk', created, model,
          choices: [],
          usage,
        });
        res.write('data: [DONE]\n\n');
        clearInterval(tick);
        try { res.end(); } catch {}
        resolve();
      } else {
        flush();
      }
    }, 60);
  });
}

// ---------------------------------------------------------------------------
// Utils + main
// ---------------------------------------------------------------------------
function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

function main() {
  const cfg = loadConfig();
  const gateway = new Gateway();
  const engine = new Engine(gateway, cfg);

  // Watch gateway.json for changes (box restarts rewrite it)
  if (fs.existsSync(path.dirname(GATEWAY_PATH))) {
    try {
      fs.watch(path.dirname(GATEWAY_PATH), (evt, fname) => {
        if (fname === 'gateway.json') {
          gateway.refreshDiscovery();
        }
      });
    } catch {}
  }

  // Initial wait for gateway
  log('waiting for gateway...');
  gateway.waitForGateway(120000).then((ok) => {
    log(ok ? 'gateway ready' : 'WARN gateway not available at startup; will retry on demand');
  });

  // Warm up the dedicated backend Agent without changing model settings.
  (async () => {
    try {
      await engine._ensureAgent();
      log('backend agent ready:', gateway.agentId);
    } catch (e) {
      log('WARN warm-up failed:', e.message, '(will retry on first request)');
    }
  })();

  startServer(engine, cfg);

  process.on('SIGTERM', () => process.exit(0));
  process.on('SIGINT', () => process.exit(0));
}

main();
