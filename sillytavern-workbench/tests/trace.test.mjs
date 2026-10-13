import test from 'node:test';
import assert from 'node:assert/strict';
import { createTrace, observeFetch, redact, snapshot } from '../extension/trace.js';

const location = { href: 'http://localhost:8000/', origin: 'http://localhost:8000' };
const path = '/api/backends/chat-completions/generate';
const body = { messages: [{ role: 'user', content: '**原文** <xml>内容</xml>' }], max_tokens: 100 };

test('preserves request arguments, returned promise, response identity and stream', async () => {
    const response = new Response('data: test\n\n', { headers: { 'content-type': 'text/event-stream' } });
    const promise = Promise.resolve(response);
    let seen;
    const host = { location, fetch(...args) { seen = { owner: this, args }; return promise; } };
    const records = [];
    const restore = observeFetch(host, x => records.push(x));
    const options = { method: 'POST', body: JSON.stringify(body), signal: new AbortController().signal };
    assert.equal(host.fetch(path, options), promise);
    assert.equal(seen.owner, host);
    assert.equal(seen.args[1], options);
    assert.equal(await promise, response);
    assert.equal(response.bodyUsed, false);
    assert.equal(records[0].status, 200);
    assert.deepEqual(records[0].body, body);
    assert.equal(await response.text(), 'data: test\n\n');
    restore();
});

test('preserves rejection and does not add an unhandled rejection on abort', async () => {
    const error = new DOMException('Cancelled', 'AbortError');
    const host = { location, fetch: () => Promise.reject(error) };
    const records = [];
    const restore = observeFetch(host, x => records.push(x));
    await assert.rejects(host.fetch(path, { method: 'POST', body: '{}' }), x => x === error);
    assert.equal(records[0].status, 'aborted');
    restore();
});

test('limits observation to same-origin, selected POST endpoints', async () => {
    const host = { location, fetch: () => Promise.resolve(new Response()) };
    const records = [];
    const restore = observeFetch(host, x => records.push(x));
    for (const [url, method] of [['/api/settings/save', 'POST'], [path, 'GET'], ['https://other.example' + path, 'POST']]) {
        await host.fetch(url, { method, body: '{}' });
    }
    assert.equal(records.length, 0);
    await host.fetch(new Request(location.origin + path, { method: 'POST', body: '{}' }));
    assert.equal(records[0].body.reason, 'unsupported-or-large-body');
    restore();
});

test('redacts credentials but keeps model parameters, text and XML intact', () => {
    assert.deepEqual(redact({ ...body, api_key: 'secret', nested: { Authorization: 'Bearer secret' },
        custom_include_headers: 'X-Token: secret', custom_url: 'https://user:secret@example.test/v1?api_key=secret' }), {
        ...body, api_key: '[redacted]', nested: { Authorization: '[redacted]' },
        custom_include_headers: '[redacted]', custom_url: 'https://redacted:redacted@example.test/v1?api_key=%5Bredacted%5D',
    });
    assert.equal(snapshot({ text: 'x'.repeat(150_000) }).truncated, true);
});

test('restore does not overwrite a later plugin wrapper and disables a retained observer', async () => {
    const original = () => Promise.resolve(new Response());
    const host = { location, fetch: original };
    let count = 0;
    const restore = observeFetch(host, () => count++);
    const observed = host.fetch;
    const outer = (...args) => observed(...args);
    host.fetch = outer;
    restore();
    assert.equal(host.fetch, outer);
    await host.fetch(path, { method: 'POST', body: '{}' });
    assert.equal(count, 0);
});

test('observation failure never prevents the original request', async () => {
    let called = false;
    const host = { location, fetch: () => { called = true; return Promise.resolve(new Response()); } };
    const restore = observeFetch(host, () => { throw new Error('observer failed'); });
    await host.fetch(path, { method: 'POST', body: '{}' });
    assert.equal(called, true);
    restore();
});

test('trace snapshots events, bounds history, clears stale world info and cleans listeners', async () => {
    const listeners = new Map();
    const context = {
        eventTypes: Object.fromEntries(['GENERATION_STARTED', 'WORLD_INFO_ACTIVATED', 'CHAT_COMPLETION_SETTINGS_READY',
            'GENERATE_AFTER_DATA', 'GENERATION_ENDED', 'GENERATION_STOPPED', 'CHAT_COMPLETION_PROMPT_READY'].map(x => [x, x])),
        eventSource: {
            on(event, fn) { (listeners.get(event) ?? listeners.set(event, []).get(event)).push(fn); },
            removeListener(event, fn) { listeners.set(event, listeners.get(event).filter(x => x !== fn)); },
        },
    };
    const emit = (name, ...args) => listeners.get(name)?.forEach(fn => fn(...args));
    const original = () => Promise.resolve(new Response());
    const host = { location, fetch: original };
    const composition = { counts: { main: 20, chatHistory: 80 }, total: 100, limit: 4096 };
    const trace = createTrace(context, host, () => composition);
    const entry = { uid: 3, content: '命中内容' };
    emit('GENERATION_STARTED', 'normal', {}, false);
    emit('WORLD_INFO_ACTIVATED', [entry]);
    emit('CHAT_COMPLETION_PROMPT_READY', { dryRun: false });
    composition.counts.main = 999;
    emit('CHAT_COMPLETION_PROMPT_READY', { dryRun: true });
    emit('CHAT_COMPLETION_SETTINGS_READY', body);
    await host.fetch(path, { method: 'POST', body: JSON.stringify(body) });
    assert.equal(trace.records[0].composition.counts.main, 20);
    assert.equal(trace.records[0].composition.total, 100);
    assert.ok(trace.records[0].timestamp > 0);
    entry.content = '后来修改';
    assert.equal(trace.records[0].worldInfo[0].content, '命中内容');
    emit('GENERATION_ENDED');
    for (let i = 0; i < 30; i++) await host.fetch(path, { method: 'POST', body: '{}' });
    assert.equal(trace.records.length, 20);
    assert.equal(trace.records.at(-1).worldInfoEvidence, 'not-observed');
    assert.equal(trace.records.at(-1).composition, null);
    trace.clear();
    assert.equal(trace.records.length, 0);
    trace.destroy();
    assert.equal(host.fetch, original);
    assert.equal([...listeners.values()].flat().length, 0);
});
