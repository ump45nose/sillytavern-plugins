/** Lightweight, read-only startup capture before importing the workbench UI. */
export function captureStartup(context) {
    if (window.workbenchStartup) return window.workbenchStartup;
    const key = 'wb-startup-history-v1';
    let history = [];
    try { history = JSON.parse(sessionStorage.getItem(key) || '[]'); if (!Array.isArray(history)) history = []; } catch { /* Session storage may be unavailable. */ }
    const id = String(performance.timeOrigin), milestones = { bootstrapMs: performance.now() }, longTasks = [];
    let taskObserver, startupCounts;
    let incompleteResources = performance.getEntriesByType('resource').length >= 250;
    performance.setResourceTimingBufferSize(4000);
    performance.addEventListener('resourcetimingbufferfull', () => { incompleteResources = true; });
    try { taskObserver = new PerformanceObserver(list => { longTasks.push(...list.getEntries().map(entry => ({ startMs: entry.startTime, durationMs: entry.duration }))); if (longTasks.length > 128) longTasks.splice(0, longTasks.length - 128); }); taskObserver.observe({ type: 'longtask', buffered: true }); } catch { /* Unsupported browser: navigation/resource metrics remain available. */ }
    const safeUrl = name => { try { const url = new URL(name); return (url.origin === location.origin ? '' : url.origin) + url.pathname; } catch { return ''; } };
    const snapshot = () => {
        const current = window.SillyTavern?.getContext?.() || context;
        const navigation = performance.getEntriesByType('navigation')[0];
        const end = milestones.workbenchReadyMs || milestones.appReadyMs || performance.now();
        const resources = performance.getEntriesByType('resource').filter(entry => entry.startTime <= end && entry.responseEnd <= end);
        return { id, startedAt: performance.timeOrigin, capturedAt: Date.now(), ready: !!milestones.appReadyMs,
            milestones: { ...milestones }, navigation: navigation ? { firstByteMs: navigation.responseStart, domContentLoadedMs: navigation.domContentLoadedEventEnd, loadMs: navigation.loadEventEnd } : {},
            counts: startupCounts || { characters: current?.characters?.length || 0, messages: current?.chat?.length || 0 },
            requestCount: resources.length, transferredBytes: resources.reduce((sum, entry) => sum + entry.transferSize, 0), incompleteResources,
            slowResources: [...resources].sort((a, b) => b.duration - a.duration).slice(0, 15).map(entry => ({ path: safeUrl(entry.name), startMs: entry.startTime, durationMs: entry.duration, transferredBytes: entry.transferSize, cacheKnown: entry.transferSize > 0 || entry.decodedBodySize > 0 })),
            longTasks: longTasks.filter(entry => entry.startMs <= end).sort((a, b) => b.durationMs - a.durationMs).slice(0, 12),
            disabledExtensions: [...(current?.extensionSettings?.disabledExtensions || [])],
        };
    };
    const save = () => {
        const report = snapshot(); history = [report, ...history.filter(item => item.id !== id)].slice(0, 5);
        try { sessionStorage.setItem(key, JSON.stringify(history)); } catch { /* Capture still works without persistence. */ }
        window.dispatchEvent(new Event('wb-startup-updated'));
    };
    const mark = (name, time = performance.now()) => { milestones[name] ??= time; save(); };
    context?.eventSource?.on(context.eventTypes.APP_INITIALIZED, () => mark('appInitializedMs'));
    context?.eventSource?.on(context.eventTypes.APP_READY, () => { const current = window.SillyTavern?.getContext?.() || context; startupCounts = { characters: current?.characters?.length || 0, messages: current?.chat?.length || 0 }; mark('appReadyMs'); setTimeout(() => taskObserver?.disconnect(), 2000); });
    setTimeout(() => { if (!milestones.appReadyMs) save(); }, 10_000);
    window.addEventListener('pagehide', save);
    const probe = { mark, snapshot, get history() { return [snapshot(), ...history.filter(item => item.id !== id)].slice(0, 5); } };
    window.workbenchStartup = probe;
    return probe;
}
