import fs from 'node:fs';
import path from 'node:path';
import http from 'node:http';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { launch, session, ready, urls, save, root } from './browser.mjs';

const run = promisify(execFile);
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
const settingsPath = path.join(root, 'runtime/validation/data/default-user/settings.json');
const original = fs.readFileSync(settingsPath, 'utf8');
const seed = JSON.parse(original);
const samples = Number(process.env.WB_BENCHMARK_SAMPLES ?? 5);
const profiles = [
    { name: 'native-disabled-extensions', disabled: ['third-party/JS-Slash-Runner', 'third-party/workbench-probe'] },
    { name: 'workbench-only', disabled: ['third-party/JS-Slash-Runner'] },
    { name: 'helper-and-workbench', disabled: [] },
];
const report = {
    checkedAt: new Date().toISOString(), samplesPerCacheMode: samples,
    methodology: {
        browser: 'Existing Chromium executable; headless; same host; 1440×900; no network throttling.',
        cold: 'Fresh browser context for each navigation; server and OS caches remain warm.',
        warm: 'Repeat navigation within the same browser context after its cold sample.',
        comparison: 'Same validation server and synthetic data; extension availability stays fixed, enablement changes.',
        ready: 'Official APP_READY event, measured from navigation start; not shell appearance.',
        interception: 'No Playwright routing during benchmarks, so HTTP cache remains enabled.',
        startup: 'Restart-to-HTTP-ready includes Docker restart command overhead; 100ms polling; existing image and persistent caches.',
        excluded: 'First-run onboarding, image download, npm installation, real model latency, production dataset and real mobile device.',
    },
    profiles: [], serverRestartMs: [],
};
const browser = await launch();

async function measure(page) {
    const started = performance.now();
    await ready(page, urls.validation);
    await page.waitForFunction(()=>!window.workbench||Boolean(window.workbench.metrics.workbenchReadyMs));
    return page.evaluate(wallMs => {
        const resources = performance.getEntriesByType('resource');
        const navigation = performance.getEntriesByType('navigation')[0];
        return {
            ...window.baselineMetrics,
            wallMs,
            domContentLoadedMs: navigation.domContentLoadedEventEnd,
            requestCount: resources.length,
            transferredBytes: resources.reduce((sum, x) => sum + x.transferSize, 0),
            probe: window.workbenchProbe?.metrics ?? null,
            slowestResources: resources.sort((a, b) => b.duration - a.duration).slice(0, 12)
                .map(x => ({ path: new URL(x.name).pathname, startMs: x.startTime, durationMs: x.duration, transferSize: x.transferSize })),
        };
    }, performance.now() - started);
}

try {
    for (const profile of profiles) {
        const current = structuredClone(seed);
        current.firstRun = false;
        current.active_character = null;
        current.active_group = null;
        current.extension_settings.disabledExtensions = profile.disabled;
        fs.writeFileSync(settingsPath, JSON.stringify(current, null, 2));
        const result = { name: profile.name, cold: [], warm: [], errors: [] };
        for (let i = 0; i < samples; i++) {
            const sample = await session(browser);
            result.cold.push(await measure(sample.page));
            result.warm.push(await measure(sample.page));
            result.errors.push(...sample.errors);
            await sample.context.close();
            console.log(profile.name, `${i + 1}/${samples}`, 'cold/warm APP_READY',
                Math.round(result.cold.at(-1).appReadyMs), Math.round(result.warm.at(-1).appReadyMs), 'ms');
        }
        const summary = values => {
            const sorted = values.map(x => x.appReadyMs).sort((a, b) => a - b);
            return { minMs: sorted[0], medianMs: sorted[Math.floor(sorted.length / 2)], maxMs: sorted.at(-1) };
        };
        result.summary = { cold: summary(result.cold), warm: summary(result.warm) };
        report.profiles.push(result);
    }
    if (report.profiles.some(x => x.errors.length)) throw new Error('Page errors occurred during benchmarking; inspect the report.');

    for (let i = 0; i < 3; i++) {
        const start = performance.now();
        await run('docker', ['compose', 'restart', '--no-deps', '-t', '2', 'baseline'], { cwd: root });
        let available = false;
        for (let attempt = 0; attempt < 200; attempt++) {
            available = await new Promise(resolve => {
                const req = http.get(urls.baseline + '/', response => { response.resume(); resolve([200, 401].includes(response.statusCode)); });
                req.on('error', () => resolve(false));
                req.setTimeout(500, () => { req.destroy(); resolve(false); });
            });
            if (available) break;
            await sleep(100);
        }
        if (!available) throw new Error('Baseline server did not become reachable after restart.');
        report.serverRestartMs.push(performance.now() - start);
    }
    report.passed = true;
} catch (error) {
    report.passed = false;
    report.failure = error.stack;
    process.exitCode = 1;
    console.error(error);
} finally {
    fs.writeFileSync(settingsPath, original);
    save('workbench-benchmark.json', report);
    await browser.close();
}
