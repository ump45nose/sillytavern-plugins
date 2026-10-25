import fs from 'node:fs';
import { launch, session, ready, urls, artifacts } from './browser.mjs';

// Protect writes inside each browser session. Do not use Playwright routing:
// it disables HTTP caching and would invalidate a cold/reload comparison.
const browser = await launch(), rows = [];
try {
  for (const enabled of [true, false]) {
    const test = await session(browser);
    await test.context.addInitScript(({ enabled }) => {
      performance.setResourceTimingBufferSize(4000);
      const original = window.fetch.bind(window);
      window.fetch = async (input, init) => {
        const url = new URL(typeof input === 'string' ? input : input.url || String(input), location.href);
        if (url.origin === location.origin && ['/api/settings/save', '/api/chats/save', '/api/chats/group/save'].includes(url.pathname))
          return new Response('{}', { headers: { 'Content-Type': 'application/json' } });
        const response = await original(input, init);
        if (!enabled && url.origin === location.origin && url.pathname === '/api/settings/get') {
          const data = await response.clone().json(), settings = JSON.parse(data.settings);
          settings.extension_settings.disabledExtensions = [...new Set([...settings.extension_settings.disabledExtensions, 'third-party/workbench-probe'])];
          data.settings = JSON.stringify(settings);
          return new Response(JSON.stringify(data), { status: response.status, headers: response.headers });
        }
        return response;
      };
    }, { enabled });
    await test.page.setViewportSize({ width: 1496, height: 817 });
    for (const navigation of ['fresh', 'reload']) {
      if (navigation === 'fresh') await ready(test.page, urls.validation);
      else {
        await test.page.reload({ waitUntil: 'domcontentloaded' });
        await test.page.waitForFunction(() => Number.isFinite(window.baselineMetrics?.appReadyMs), null, { timeout: 90_000 });
      }
      if (enabled) await test.page.waitForFunction(() => window.workbench?.mounted && window.workbench.metrics.workbenchReadyMs);
      const row = await test.page.evaluate(() => {
        const c = SillyTavern.getContext(), nav = performance.getEntriesByType('navigation')[0], end = window.workbench?.metrics.workbenchReadyMs || baselineMetrics.appReadyMs;
        const resources = performance.getEntriesByType('resource').filter(entry => entry.responseEnd <= end);
        return { appReadyMs: baselineMetrics.appReadyMs, workbenchReadyMs: window.workbench?.metrics.workbenchReadyMs,
          firstByteMs: nav.responseStart, domContentLoadedMs: nav.domContentLoadedEventEnd, requests: resources.length,
          transferredBytes: resources.reduce((sum, entry) => sum + entry.transferSize, 0),
          characters: c.characters.length, messages: c.chat.length, helperPresent: typeof TavernHelper !== 'undefined',
          hideLoaderInContext: typeof c.hideLoader === 'function',
          slowResources: [...resources].sort((a, b) => b.duration - a.duration).slice(0, 12).map(entry => ({ path: new URL(entry.name).pathname, durationMs: entry.duration, transferredBytes: entry.transferSize })) };
      });
      rows.push({ workbench: enabled, navigation, ...row });
      console.log(JSON.stringify({ workbench: enabled, navigation, appReadyMs: row.appReadyMs, workbenchReadyMs: row.workbenchReadyMs, firstByteMs: row.firstByteMs, requests: row.requests }));
    }
    if (test.errors.length) throw new Error(test.errors.join('\n'));
    await test.context.close();
  }
  fs.writeFileSync(artifacts + '/startup-readonly-benchmark.json', JSON.stringify({ checkedAt: new Date().toISOString(), viewport: { width: 1496, height: 817 }, method: 'session-only fetch write protection; no request routing; original account and chats unchanged', rows }, null, 2));
} finally { await browser.close(); }
