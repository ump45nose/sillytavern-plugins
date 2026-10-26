// Shared runtime for the perf modules: settings namespace, ST context and one fetch hook chain.

export const NAMESPACE = 'wbPerf';
export const TAG = '[wb-perf]';

export const ctx = () => globalThis.SillyTavern.getContext();

/** Reads `extension_settings.wbPerf`; absent keys mean "on". Nothing is written until the panel changes a switch. */
export function settings() {
    const stored = ctx().extensionSettings[NAMESPACE];
    return { enabled: stored?.enabled !== false, modules: { ...stored?.modules } };
}

export function moduleEnabled(id) {
    const s = settings();
    return s.enabled && s.modules[id] !== false;
}

/** The only settings write this extension makes, and only inside its own namespace. */
export function saveSettings(patch) {
    const c = ctx(), current = settings();
    c.extensionSettings[NAMESPACE] = { ...current, ...patch, modules: { ...current.modules, ...patch.modules } };
    c.saveSettingsDebounced();
}

export function stopEvent(event) {
    event.preventDefault();
    event.stopImmediatePropagation();
}

// One wrapper serves every module that inspects requests. Handlers run outermost-first and each
// either returns a Response promise or calls next(input, init).
const fetchHandlers = new Set();
let baseFetch = null, wrappedFetch = null;

export function addFetchHandler(handler) {
    if (!wrappedFetch) {
        baseFetch = globalThis.fetch;
        wrappedFetch = function wbPerfFetch(input, init) {
            const chain = [...fetchHandlers];
            const run = (i, nextInput, nextInit) =>
                i < chain.length ? chain[i](nextInput, nextInit, (a, b) => run(i + 1, a, b)) : baseFetch.call(globalThis, nextInput, nextInit);
            return run(0, input, init);
        };
        globalThis.fetch = wrappedFetch;
    }
    fetchHandlers.add(handler);
    return () => {
        fetchHandlers.delete(handler);
        // Unwrap only while nothing has wrapped fetch after us; otherwise the wrapper stays as a pass-through.
        if (!fetchHandlers.size && globalThis.fetch === wrappedFetch) {
            globalThis.fetch = baseFetch;
            wrappedFetch = baseFetch = null;
        }
    };
}

/** "/api/settings/save" for a string, URL or Request; null when unparseable. */
export function requestUrl(input) {
    try {
        return new URL(typeof input === 'string' ? input : input instanceof URL ? input.href : input.url, location.href);
    } catch {
        return null;
    }
}
