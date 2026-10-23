'use strict';

// Native applications only. Provider operations are injected from Electron main;
// this transport never loads credentials or implements a supplier protocol.
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');

const PROVIDERS = Object.freeze([
  { id: 'codex', name: 'Codex', methods: ['oauth', 'discover'], multiple: true },
  { id: 'cursor', name: 'Cursor', methods: ['credential', 'discover'], multiple: true },
  { id: 'antigravity', name: 'Antigravity', methods: ['oauth', 'discover'], multiple: true },
  { id: 'copilot', name: 'GitHub Copilot', methods: ['device', 'discover'], multiple: false },
  { id: 'grok', name: 'Grok', methods: ['credential', 'discover'], multiple: false },
  { id: 'zai', name: 'Z.ai', methods: ['credential', 'discover'], multiple: false },
  { id: 'claude', name: 'Claude', methods: ['discover'], multiple: false }
]);
const TERMINAL = new Set(['succeeded', 'failed', 'cancelled', 'expired']);
const fail = (code, status = 400) => Object.assign(new Error(code), { code, status });

function safeAccount(row) {
  if (!row?.accountKey || !PROVIDERS.some(p => p.id === row.provider)) return null;
  return {
    binding: { collector: 'token_monitor', provider: row.provider, account: row.accountKey,
      account_email: row.accountEmail || '', profile: row.accountName || '' },
    label: row.accountEmail || row.accountName || row.accountLabel || row.provider,
    plan: row.planLabel || '', status: row.status || 'unavailable',
    observedAt: row.updatedAt || null, stale: row.stale === true
  };
}

async function startLocalAccountControl({ dataDir, accounts, connect, cancel, select }) {
  const secret = crypto.randomBytes(32).toString('hex');
  const flows = new Map();
  const discovery = path.join(dataDir, 'local-account-control.json');
  let port;
  function snapshot(flow) {
    const { id, provider, status, phase, loginUrl, userCode, workspaces, account, syncStatus, error } = flow;
    return { id, provider, status, phase, loginUrl, userCode, workspaces, account, syncStatus, error };
  }
  function finish(flow, status, error) {
    if (TERMINAL.has(flow.status)) return;
    flow.status = status; flow.error = error; flow.endedAt = Date.now();
    clearTimeout(flow.timer);
  }
  const server = http.createServer(async (req, res) => {
    const reply = (status, data) => {
      res.writeHead(status, { 'content-type': 'application/json', 'cache-control': 'no-store' });
      res.end(JSON.stringify(data));
    };
    try {
      const received = Buffer.from(String(req.headers.authorization || ''));
      const expected = Buffer.from('Bearer ' + secret);
      if (req.headers.origin || req.headers.host !== `127.0.0.1:${port}`
        || received.length !== expected.length || !crypto.timingSafeEqual(received, expected)) throw fail('unauthorized', 401);
      const url = new URL(req.url, `http://127.0.0.1:${port}`);
      if (url.search) throw fail('invalid_request');
      const body = async () => {
        let size = 0; const chunks = [];
        for await (const chunk of req) {
          size += chunk.length;
          if (size > 32768) throw fail('body_too_large', 413);
          chunks.push(chunk);
        }
        const value = JSON.parse(Buffer.concat(chunks).toString('utf8') || '{}');
        if (!value || typeof value !== 'object' || Array.isArray(value)) throw fail('invalid_request');
        return value;
      };
      for (const [id, flow] of flows) if (flow.endedAt && Date.now() - flow.endedAt > 600000) flows.delete(id);
      if (req.method === 'GET' && url.pathname === '/v1/capabilities') return reply(200, { version: 1, providers: PROVIDERS });
      if (req.method === 'GET' && url.pathname === '/v1/accounts') return reply(200, { accounts: accounts().map(safeAccount).filter(Boolean) });
      if (req.method === 'POST' && url.pathname === '/v1/connections') {
        const input = await body();
        if (Object.keys(input).some(k => !['provider', 'method', 'requestId', 'credential', 'region', 'account', 'replace'].includes(k))) throw fail('invalid_request');
        const provider = PROVIDERS.find(p => p.id === input.provider);
        if (!provider?.methods.includes(input.method) || typeof input.requestId !== 'string'
          || !/^[a-zA-Z0-9-]{8,80}$/.test(input.requestId)) throw fail('invalid_request');
        if (input.credential !== undefined && (input.method !== 'credential' || typeof input.credential !== 'string'
          || !input.credential.trim() || input.credential.length > 16384)) throw fail('invalid_credential');
        if (input.method === 'credential' && !input.credential) throw fail('invalid_credential');
        if (input.region !== undefined && (provider.id !== 'zai' || !['global', 'bigmodel-cn'].includes(input.region))) throw fail('invalid_region');
        if (input.account !== undefined && (typeof input.account !== 'string' || input.account.length > 256)) throw fail('invalid_request');
        if (input.replace !== undefined && typeof input.replace !== 'boolean') throw fail('invalid_request');
        const digest = crypto.createHmac('sha256', secret).update(JSON.stringify(input)).digest('hex');
        const existing = [...flows.values()].find(f => f.requestId === input.requestId);
        if (existing) {
          if (existing.digest !== digest) throw fail('request_conflict', 409);
          return reply(200, snapshot(existing));
        }
        if (flows.size >= 100 || [...flows.values()].some(f => f.provider === provider.id && !TERMINAL.has(f.status))) throw fail('login_in_progress', 409);
        if (!provider.multiple && input.method !== 'discover' && !input.replace
          && accounts().some(a => a.provider === provider.id && a.accountKey)) throw fail('replacement_required', 409);
        const flow = { id: crypto.randomUUID(), requestId: input.requestId, digest, provider: provider.id, status: 'pending', phase: 'starting', controller: new AbortController(), committed: false };
        flows.set(flow.id, flow);
        const context = {
          id: flow.id, startedAt: Date.now(), signal: flow.controller.signal,
          commit() { if (flow.controller.signal.aborted) throw fail('cancelled'); flow.committed = true; },
          emit(event) {
            if (TERMINAL.has(flow.status)) return;
            flow.phase = event.phase || 'authorizing';
            // Provider output can contain credentials. Only these presentation fields cross.
            if (event.loginUrl || event.verificationUrl) {
              try {
                const u = new URL(event.loginUrl || event.verificationUrl);
                const hosts = { codex: ['auth.openai.com'], copilot: ['github.com'], antigravity: ['accounts.google.com'] };
                if (u.protocol === 'https:' && (hosts[flow.provider] || []).includes(u.hostname)) flow.loginUrl = u.href;
              } catch (_) {}
            }
            if (typeof event.userCode === 'string' && /^[A-Z0-9 -]{1,40}$/i.test(event.userCode)) flow.userCode = event.userCode;
            if (Array.isArray(event.workspaces)) flow.workspaces = event.workspaces.map(w => ({ id: String(w.id), label: String(w.label || w.id), workspaceKind: String(w.workspaceKind || '') }));
          }
        };
        flow.timer = setTimeout(() => {
          if (!flow.committed) { flow.controller.abort(); cancel?.(flow.provider, flow.id); finish(flow, 'expired', 'login_expired'); }
        }, 180000);
        flow.timer.unref();
        reply(202, snapshot(flow));
        Promise.resolve().then(() => connect(input, context)).then(result => {
          if (!result?.account?.binding?.account) throw fail('account_unavailable');
          flow.account = result.account; flow.syncStatus = result.syncStatus || 'pending';
          finish(flow, 'succeeded');
        }).catch(error => finish(flow, flow.controller.signal.aborted ? 'cancelled' : 'failed',
          ['local_mode_required', 'runtime_unavailable', 'account_unavailable', 'invalid_credential', 'replacement_required'].includes(error?.code) ? error.code : 'connection_failed'));
        return;
      }
      const match = url.pathname.match(/^\/v1\/connections\/([a-f0-9-]{36})(\/selection)?$/);
      if (!match) throw fail('not_found', 404);
      const flow = flows.get(match[1]);
      if (!flow) throw fail('connection_expired', 404);
      if (req.method === 'GET' && !match[2]) return reply(200, snapshot(flow));
      if (req.method === 'DELETE' && !match[2]) {
        if (TERMINAL.has(flow.status)) return reply(200, snapshot(flow));
        if (flow.committed) throw fail('too_late', 409);
        flow.controller.abort(); cancel?.(flow.provider, flow.id); finish(flow, 'cancelled');
        return reply(200, snapshot(flow));
      }
      if (req.method === 'POST' && match[2]) {
        const input = await body();
        if (Object.keys(input).some(k => k !== 'workspaceId') || !flow.workspaces?.some(w => w.id === input.workspaceId)
          || TERMINAL.has(flow.status)) throw fail('invalid_selection');
        if (!select?.(flow.id, input.workspaceId)) throw fail('stale_selection', 409);
        flow.workspaces = undefined;
        return reply(200, snapshot(flow));
      }
      throw fail('not_found', 404);
    } catch (error) {
      // Never include supplier or transport exception messages in responses.
      reply(error?.status || 400, { error: error?.status ? error.code : 'invalid_request' });
    }
  });
  server.requestTimeout = 10000;
  server.headersTimeout = 10000;
  await new Promise((resolve, reject) => { server.once('error', reject); server.listen(0, '127.0.0.1', resolve); });
  port = server.address().port;
  fs.mkdirSync(dataDir, { recursive: true, mode: 0o700 });
  const temporary = discovery + '.' + process.pid;
  fs.writeFileSync(temporary, JSON.stringify({ version: 1, port, token: secret, pid: process.pid }), { mode: 0o600 });
  fs.renameSync(temporary, discovery);
  return {
    async close() {
      for (const flow of flows.values()) {
        if (!TERMINAL.has(flow.status) && !flow.committed) { flow.controller.abort(); cancel?.(flow.provider, flow.id); }
        clearTimeout(flow.timer);
      }
      try { if (JSON.parse(fs.readFileSync(discovery, 'utf8')).token === secret) fs.unlinkSync(discovery); } catch (_) {}
      server.closeAllConnections(); server.close();
    }
  };
}

module.exports = { startLocalAccountControl, safeAccount };
