const GENERATION_PATHS = new Set([
    '/api/backends/chat-completions/generate',
    '/api/backends/text-completions/generate',
]);
const SECRET_KEY = /^(authorization|api[_-]?key|password|secret|access[_-]?token|refresh[_-]?token|custom_include_headers)$/i;
const MAX_BODY_BYTES = 128 * 1024;
const MAX_RECORDS = 20;
// randomUUID requires HTTPS; getRandomValues also works on LAN HTTP.
const makeId = () => globalThis.crypto.randomUUID?.() ??
    Array.from(globalThis.crypto.getRandomValues(new Uint8Array(16)), value => value.toString(16).padStart(2, '0')).join('');

export function redact(value, key = '') {
    if (SECRET_KEY.test(key)) return '[redacted]';
    if (Array.isArray(value)) return value.map(item => redact(item));
    if (value && typeof value === 'object') {
        return Object.fromEntries(Object.entries(value).map(([name, item]) => [name, redact(item, name)]));
    }
    if (typeof value === 'string' && /url$/i.test(key)) {
        try {
            const url = new URL(value);
            if (url.username) url.username = 'redacted';
            if (url.password) url.password = 'redacted';
            for (const name of url.searchParams.keys()) {
                if (SECRET_KEY.test(name) || name === 'token') url.searchParams.set(name, '[redacted]');
            }
            return url.href;
        } catch { /* Not a URL; preserve the input. */ }
    }
    return value;
}

export function snapshot(value) {
    try {
        const json = JSON.stringify(value);
        if (new TextEncoder().encode(json).byteLength > MAX_BODY_BYTES) return { truncated: true, reason: 'body-size-limit' };
        return redact(JSON.parse(json));
    } catch {
        return { unavailable: true, reason: 'not-serializable' };
    }
}

/** Observe only same-origin generation POSTs. Never reads the response body. */
export function observeFetch(host, onRecord, now = () => performance.now()) {
    const original = host.fetch;
    let active = true;
    function observed(input, init) {
        let record;
        try {
            const url = new URL(typeof input === 'string' || input instanceof URL ? input : input.url, host.location.href);
            const method = init?.method ?? input?.method ?? 'GET';
            if (active && url.origin === host.location.origin && method.toUpperCase() === 'POST' && GENERATION_PATHS.has(url.pathname)) {
                // Native ST generation uses a JSON string. Other body types are
                // intentionally left unread to avoid buffering/cloning streams.
                record = {
                    id: makeId(), atMs: now(), timestamp: Date.now(), path: url.pathname,
                    capturePoint: 'browser-to-sillytavern', status: 'pending',
                    body: typeof init?.body === 'string' && new TextEncoder().encode(init.body).byteLength <= MAX_BODY_BYTES
                        ? snapshot(JSON.parse(init.body)) : { unavailable: true, reason: 'unsupported-or-large-body' },
                };
                onRecord(record);
            }
        } catch { /* Observation must never prevent a request. */ }
        let result;
        try {
            result = Reflect.apply(original, this, arguments);
        } catch (error) {
            if (record) { record.status = 'failed'; record.elapsedMs = now() - record.atMs; }
            throw error;
        }
        if (record) {
            result.then(response => {
                record.status = response.status;
                record.elapsedMs = now() - record.atMs; // Time to headers, not time to completed generation.
            }, error => {
                record.status = error?.name === 'AbortError' ? 'aborted' : 'failed';
                record.elapsedMs = now() - record.atMs;
            });
        }
        return result;
    }
    host.fetch = observed;
    return () => {
        active = false;
        if (host.fetch === observed) host.fetch = original;
    };
}

/** @param {() => any} inspectComposition */
export function createTrace(context, host = window, inspectComposition = () => null) {
    const records = [];
    const listeners = [];
    let pending = {};
    let generation;
    const listen = (name, handler) => {
        const event = context.eventTypes[name];
        if (!event) return;
        context.eventSource.on(event, handler);
        listeners.push([event, handler]);
    };
    listen('GENERATION_STARTED', (type, _options, dryRun) => {
        if (!dryRun) {
            generation = { id: makeId(), type };
            pending = {};
        }
    });
    listen('CHAT_COMPLETION_PROMPT_READY', data => {
        if (!data?.dryRun) { try { pending.composition = snapshot(inspectComposition()); } catch { /* optional capability */ } }
    });
    listen('WORLD_INFO_ACTIVATED', entries => { pending.worldInfo = snapshot(entries); });
    listen('CHAT_COMPLETION_SETTINGS_READY', body => { pending.event = 'CHAT_COMPLETION_SETTINGS_READY'; pending.assembled = snapshot(body); });
    listen('GENERATE_AFTER_DATA', (body, dryRun) => {
        if (!dryRun) { pending.event = 'GENERATE_AFTER_DATA'; pending.assembled = snapshot(body); }
    });
    for (const name of ['GENERATION_ENDED', 'GENERATION_STOPPED']) {
        listen(name, () => { generation = undefined; pending = {}; });
    }
    const restoreFetch = observeFetch(host, record => {
        Object.assign(record, {
            generation: generation ? { ...generation } : null,
            assemblyEvent: pending.event ?? null,
            assembled: pending.assembled ?? null,
            worldInfo: pending.worldInfo ?? [],
            composition: pending.composition ?? null,
            worldInfoEvidence: pending.worldInfo ? 'WORLD_INFO_ACTIVATED' : 'not-observed',
        });
        pending = {};
        records.push(record);
        if (records.length > MAX_RECORDS) records.shift();
    });
    return {
        records,
        clear: () => { records.length = 0; pending = {}; },
        destroy: () => {
            restoreFetch();
            for (const [event, handler] of listeners) context.eventSource.removeListener(event, handler);
            records.length = 0;
            pending = {};
        },
    };
}
