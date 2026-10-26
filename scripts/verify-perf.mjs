import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { launch, session as baseSession, ready, urls, createCharacter, root } from './browser.mjs';

// verify:perf — the wb-perf extension (perf-extension/) on the local validation instance:
// each module's switch takes effect, switching everything off leaves native behaviour, and the
// gzip hook round-trips through the real server. Writes only a synthetic world book (deleted at the
// end), the shared WorkbenchFixture character, and a temporary key inside extension_settings.wbPerf.
const dir = 'artifacts/perf'; fs.mkdirSync(dir, { recursive: true });
const checks = [], pass = (name, details) => { checks.push({ name, passed: true, details }); console.log('PASS', name, JSON.stringify(details ?? {})); };
const BOOK = 'WbPerfFixture';
// gzip skips loopback hosts, so the gzip checks open the instance through this machine's LAN address.
// Private ranges only: VPN/tunnel interfaces often carry addresses the instance cannot be reached on.
const lan = process.env.WB_LAN_HOST ?? Object.values(os.networkInterfaces()).flat()
    .find(i => i?.family === 'IPv4' && !i.internal && /^(192\.168|10)\.|^172\.(1[6-9]|2\d|3[01])\./.test(i.address))?.address;
const lanUrl = lan && urls.validation.replace(/\/\/[^:]+:/, `//${lan}:`);

// Shared instances link wb-perf to whichever checkout prepared them; serve this checkout's copy.
const perfDir = path.join(root, 'perf-extension');
async function session(browser) {
    const result = await baseSession(browser);
    await result.context.route('**/scripts/extensions/third-party/wb-perf/**', route => {
        const file = path.join(perfDir, decodeURIComponent(new URL(route.request().url()).pathname.split('/wb-perf/')[1]));
        return file.startsWith(perfDir + path.sep) && fs.existsSync(file) ? route.fulfill({ path: file }) : route.fulfill({ status: 404, body: '' });
    });
    return result;
}

const regexScript = (id, name) => ({ id, scriptName: name, findRegex: '/wbperf-never-matches/g', replaceString: '', trimStrings: [], placement: [2], disabled: false, markdownOnly: true, promptOnly: false, runOnEdit: true, substituteRegex: 0, minDepth: null, maxDepth: null });

/** Session-only settings: never saved, so the test account keeps its own. */
async function overrideSettings(page, edit) {
    await page.route('**/api/settings/save', route => route.fulfill({ json: {} }));
    await page.route('**/api/settings/get', async route => {
        const response = await route.fetch(), data = await response.json(), s = JSON.parse(data.settings);
        edit(s);
        data.settings = JSON.stringify(s);
        await route.fulfill({ response, json: data });
    });
}
// Records whether the startup splash was still up when APP_INITIALIZED fired (just before ST hides it itself).
const watchSplash = page => page.addInitScript(() => {
    const timer = setInterval(() => {
        let c; try { c = window.SillyTavern?.getContext?.(); } catch { return; }
        if (!c?.eventSource) return;
        clearInterval(timer);
        c.eventSource.on(c.eventTypes.APP_INITIALIZED, () => { window.__splashAtInit = c.loader.active().some(h => h.slug === 'app-init'); });
    }, 5);
});
/** Request start/finish times for the three startup endpoints. */
function watchStartup(page) {
    const seen = [];
    const paths = ['/api/avatars/get', '/api/characters/all', '/api/backgrounds/all'];
    page.on('request', r => { const p = new URL(r.url()).pathname; if (paths.includes(p)) seen.push({ p, start: Date.now(), r }); });
    page.on('requestfinished', r => { const x = seen.find(s => s.r === r); if (x) x.end = Date.now(); });
    return () => Object.fromEntries(paths.map(p => [p, seen.filter(s => s.p === p)]));
}
const setModule = (page, id, on) => page.evaluate(([id, on]) => {
    const input = id ? document.querySelector(`#wb-perf-settings input[data-module="${id}"]`) : document.querySelector('#wb-perf-settings [data-master]');
    input.checked = on;
    input.dispatchEvent(new Event('change', { bubbles: true }));
    return wbPerf.status();
}, [id, on]);

/** Event listeners on document and window whose handler comes from a wb-perf script (via CDP). */
async function extensionListeners(page) {
    const cdp = await page.context().newCDPSession(page), scripts = new Map();
    cdp.on('Debugger.scriptParsed', e => scripts.set(e.scriptId, e.url));
    await cdp.send('Debugger.enable');
    const found = [];
    for (const target of ['document', 'window']) {
        const { result } = await cdp.send('Runtime.evaluate', { expression: target });
        const { listeners } = await cdp.send('DOMDebugger.getEventListeners', { objectId: result.objectId });
        for (const l of listeners) if (scripts.get(l.scriptId)?.includes('/wb-perf/')) found.push(`${target}:${l.type}`);
    }
    await cdp.detach();
    return found;
}

const browser = await launch();
let page, errors = [], passed = false;
const pages = [];
try {
    assert(lanUrl, 'no LAN IPv4 address for the gzip checks');

    // ---------- A: defaults, workbench mounted, LAN address ----------
    ({ page, errors } = await session(browser)); pages.push(page);
    await watchSplash(page);
    const startupA = watchStartup(page);
    await ready(page, lanUrl, { probe: true });
    const statusA = await page.evaluate(() => wbPerf.status());
    for (const [id, s] of Object.entries(statusA)) assert(s.active && !s.problem, `${id}: ${JSON.stringify(s)}`);
    assert(await page.locator('#wb-perf-settings input[data-module]').count() === 6);
    pass('all six modules install on 1.19.0 and the single panel lists them', statusA);

    const runs = startupA();
    for (const [p, list] of Object.entries(runs)) assert.equal(list.length, 1, `${p} requested ${list.length} times`);
    const chars = runs['/api/characters/all'][0], bgs = runs['/api/backgrounds/all'][0];
    assert(bgs.start <= chars.end, 'prefetch issues backgrounds/all before characters/all has finished');
    const counts = await page.evaluate(async () => {
        const c = SillyTavern.getContext();
        const fresh = await (await fetch('/api/characters/all', { method: 'POST', headers: c.getRequestHeaders(), body: '{}' })).json();
        return { loaded: c.characters.length, server: fresh.length };
    });
    assert.equal(counts.loaded, counts.server);
    pass('startup prefetch: the three lists are requested once, in parallel, and the native callers get them', { spreadMs: Math.max(...Object.values(runs).map(l => l[0].start)) - Math.min(...Object.values(runs).map(l => l[0].start)), ...counts });
    assert.equal(await page.evaluate(() => window.__splashAtInit), true);
    pass('early splash removal stays off while the workbench is going to mount');

    // gzip: a settings save over the 64 KB threshold, round-tripped through the real server.
    const encodings = [];
    page.on('request', r => { const p = new URL(r.url()).pathname; if (p === '/api/settings/save' || p === '/api/worldinfo/edit') encodings.push({ p, enc: r.headers()['content-encoding'] ?? null }); });
    const saved = await page.evaluate(async () => {
        const c = SillyTavern.getContext(), had = 'wbPerf' in c.extensionSettings, before = structuredClone(c.extensionSettings.wbPerf);
        c.extensionSettings.wbPerf = { ...before, verifyPad: 'x'.repeat(70_000) };
        await (await import('/script.js')).saveSettings();
        const read = JSON.parse((await (await fetch('/api/settings/get', { method: 'POST', headers: c.getRequestHeaders(), body: '{}' })).json()).settings);
        if (had) c.extensionSettings.wbPerf = before; else delete c.extensionSettings.wbPerf;
        await (await import('/script.js')).saveSettings();
        return read.extension_settings.wbPerf?.verifyPad?.length;
    });
    assert.equal(saved, 70_000);
    assert.deepEqual(encodings.filter(e => e.p === '/api/settings/save').map(e => e.enc), ['gzip', null], JSON.stringify(encodings));
    pass('a large settings save goes out gzip-compressed and the server stores it intact; a small one stays plain', { encodings });

    // gzip fallback: the server rejects the compressed body once; the hook resends it uncompressed.
    encodings.length = 0;
    await page.route('**/api/worldinfo/edit', route => route.request().headers()['content-encoding'] === 'gzip' ? route.fulfill({ status: 500, body: 'nope' }) : route.fallback());
    const book = { entries: Object.fromEntries(Array.from({ length: 4 }, (_, i) => [i, { uid: i, key: ['k' + i], keysecondary: [], comment: `条目 ${i + 1}`, content: (i === 0 ? 'y'.repeat(70_000) : '内容 ' + i), constant: false, selective: true, order: 100, position: 0, disable: false, displayIndex: i, addMemo: true, probability: 100, useProbability: true, depth: 4 }])) };
    const fallback = await page.evaluate(async ([name, data]) => {
        const c = SillyTavern.getContext();
        const r = await fetch('/api/worldinfo/edit', { method: 'POST', headers: c.getRequestHeaders(), body: JSON.stringify({ name, data }) });
        const back = await (await fetch('/api/worldinfo/get', { method: 'POST', headers: c.getRequestHeaders(), body: JSON.stringify({ name }) })).json();
        return { ok: r.ok, length: back.entries?.[0]?.content?.length };
    }, [BOOK, book]);
    await page.unroute('**/api/worldinfo/edit');
    assert.deepEqual(fallback, { ok: true, length: 70_000 });
    assert.deepEqual(encodings.map(e => e.enc), ['gzip', null]);
    pass('a failed compressed save is retried uncompressed and succeeds', { encodings });
    assert.deepEqual(errors, []);
    await page.context().close();

    // ---------- B: native UI (workbench not loaded), settings saves blocked ----------
    ({ page, errors } = await session(browser)); pages.push(page);
    await overrideSettings(page, s => {
        s.extension_settings.disabledExtensions = [...(s.extension_settings.disabledExtensions ?? []), 'third-party/workbench-probe'];
        s.extension_settings.regex = [regexScript('wbperf-a', 'WbPerf A'), regexScript('wbperf-b', 'WbPerf B')];
        delete s.extension_settings.wbPerf;
    });
    await watchSplash(page);
    await ready(page, urls.validation);
    assert.equal(await page.evaluate(() => !!window.workbench), false);
    assert.equal(await page.evaluate(() => window.__splashAtInit), false);
    pass('without the workbench the startup splash is lifted at SETTINGS_LOADED, before APP_INITIALIZED');
    await createCharacter(page);
    await page.waitForFunction(() => document.querySelectorAll('#chat .mes').length > 0);

    // Module 1: render(true) draws at once; the dry-run runs once in the background. 'chat' goes through
    // renderDebounced, the path CHAT_LOADED / MESSAGE_RECEIVED / model changes take.
    const presetProbe = path => page.evaluate(async path => {
        const pm = (await import('/scripts/openai.js')).promptManager, sleep = ms => new Promise(r => setTimeout(r, ms));
        const tryGenerate = pm.tryGenerate, items = pm.renderPromptManagerListItems;
        let tries = 0, renders = 0;
        pm.tryGenerate = () => { tries++; return sleep(1500); };
        pm.renderPromptManagerListItems = function (...args) { renders++; return items.apply(this, args); };
        try {
            // Let renders started by chat loading (1 s debounced) finish first, so only the calls below are counted.
            for (let seen = -1; seen !== tries + renders;) { seen = tries + renders; await sleep(2500); }
            tries = 0; renders = 0;
            if (path === 'chat') pm.renderDebounced();
            else { pm.render(true); pm.render(true); pm.render(true); }
            // Toggles: 500 ms in; chat: 500 ms after the 1 s debounce. Either way before a 1.5 s dry-run could end.
            await sleep(path === 'chat' ? 1500 : 500); const early = renders;
            await sleep(2500);
            return { early, renders, tries };
        } finally {
            pm.tryGenerate = tryGenerate;
            delete pm.renderPromptManagerListItems;
        }
    }, path);
    const presetOn = { toggle: await presetProbe('toggle'), chat: await presetProbe('chat') };
    assert(presetOn.toggle.early >= 1 && presetOn.toggle.tries === 1 && presetOn.toggle.renders > presetOn.toggle.early, JSON.stringify(presetOn));
    assert(presetOn.chat.early >= 1 && presetOn.chat.tries === 1 && presetOn.chat.renders > presetOn.chat.early, JSON.stringify(presetOn));
    await setModule(page, 'presetDryRun', false);
    const presetOff = { toggle: await presetProbe('toggle'), chat: await presetProbe('chat') };
    assert(presetOff.toggle.early === 0 && presetOff.toggle.tries === 3, JSON.stringify(presetOff));
    assert(presetOff.chat.early === 0 && presetOff.chat.tries === 1, JSON.stringify(presetOff));
    pass('preset panel: toggles and chat-driven re-renders redraw before the token dry-run, three quick toggles cost one dry-run; off restores native', { on: presetOn, off: presetOff });

    // Module 3: inline drawers animate with Web Animations instead of jQuery height steps.
    await page.locator('#extensions-settings-button .drawer-toggle').click();
    const drawerProbe = () => page.evaluate(async () => {
        const toggle = document.querySelector('#wb-perf-settings > .inline-drawer-toggle'), content = toggle.nextElementSibling;
        toggle.click();
        const sample = { waapi: content.getAnimations().length, jquery: jQuery(content).is(':animated'), height: content.style.height };
        await new Promise(r => setTimeout(r, 700));
        const open = getComputedStyle(content).display !== 'none';
        toggle.click();
        await new Promise(r => setTimeout(r, 700));
        return { ...sample, open, closed: getComputedStyle(content).display === 'none' };
    });
    const drawerOn = await drawerProbe();
    assert(drawerOn.waapi === 1 && !drawerOn.jquery && drawerOn.open && drawerOn.closed, JSON.stringify(drawerOn));
    await setModule(page, 'drawerAnimation', false);
    const drawerOff = await drawerProbe();
    assert(drawerOff.waapi === 0 && drawerOff.jquery && drawerOff.open && drawerOff.closed, JSON.stringify(drawerOff));
    await setModule(page, 'drawerAnimation', true);
    pass('drawers: open/close with one compositor animation and no height steps; off restores jQuery slideToggle', { on: drawerOn, off: drawerOff });

    // Module 2: toggling regex scripts while the panel is open does not re-render the chat; closing it does once.
    const mark = () => page.evaluate(() => document.querySelectorAll('#chat .mes').forEach(m => { m.dataset.wbMark = '1'; }));
    const marked = () => page.evaluate(() => [...document.querySelectorAll('#chat .mes')].every(m => m.dataset.wbMark === '1'));
    const regexDrawer = page.locator('.regex_settings > .inline-drawer > .inline-drawer-toggle');
    await regexDrawer.click();
    const label = page.locator('#saved_regex_scripts .regex-script-label#wbperf-a');
    await label.waitFor();
    await mark();
    await label.locator('.regex-toggle-on').click();
    await page.waitForTimeout(1200);
    assert.equal(await page.evaluate(() => SillyTavern.getContext().extensionSettings.regex.find(s => s.id === 'wbperf-a').disabled), true);
    assert.equal(await label.locator('.disable_regex').isChecked(), true);
    assert.equal(await marked(), true, 'single toggle must not reload the chat while the panel is open');
    await page.locator('label[for="regex_bulk_edit"]').click();
    await page.locator('#saved_regex_scripts .regex-script-label#wbperf-b .regex_bulk_checkbox').check();
    await label.locator('.regex_bulk_checkbox').check();
    await page.locator('#bulk_disable_regex').click();
    await page.waitForTimeout(800);
    const bulk = await page.evaluate(() => SillyTavern.getContext().extensionSettings.regex.map(s => s.disabled));
    assert.deepEqual(bulk, [true, true]);
    assert.equal(await marked(), true, 'bulk toggle must not reload the chat while the panel is open');
    await regexDrawer.click();
    await page.waitForFunction(() => ![...document.querySelectorAll('#chat .mes')].every(m => m.dataset.wbMark === '1'), null, { timeout: 5000 });
    pass('regex panel: single and bulk toggles keep the chat; closing the panel reloads it once');
    await setModule(page, 'regexRefresh', false);
    await regexDrawer.click();
    await mark();
    await page.locator('#saved_regex_scripts .regex-script-label#wbperf-a .regex-toggle-off').click();
    await page.waitForFunction(() => ![...document.querySelectorAll('#chat .mes')].every(m => m.dataset.wbMark === '1'), null, { timeout: 5000 });
    pass('regex panel off: a toggle reloads the chat at once (native)');
    await setModule(page, 'regexRefresh', true);
    await regexDrawer.click();
    await page.locator('#extensions-settings-button .drawer-toggle').click();

    // Module 4: dragging a world info entry moves only an indicator; release reorders and saves once.
    await page.evaluate(async name => {
        const wi = await import('/scripts/world-info.js');
        await wi.updateWorldInfoList();
        jQuery('#world_editor_select').val(String(wi.world_names.indexOf(name))).trigger('change');
    }, BOOK);
    await page.locator('#WIDrawerIcon').click();
    await page.waitForFunction(() => document.getElementById('WorldInfo').classList.contains('openDrawer') && !jQuery('#WorldInfo').is(':animated'));
    await page.evaluate(() => { const o = [...document.querySelectorAll('#world_info_sort_order option')].find(o => jQuery(o).data('rule') === 'custom'); jQuery('#world_info_sort_order').val(o.value).trigger('change'); });
    const entries = page.locator('#world_popup_entries_list > .world_entry');
    await page.waitForFunction(() => document.querySelectorAll('#world_popup_entries_list > .world_entry .drag-handle').length === 4);
    const order = () => page.evaluate(() => [...document.querySelectorAll('#world_popup_entries_list > .world_entry')].map(e => e.querySelector('textarea[name="comment"]').value));
    const before = await order();
    // The drawer opens with a height transition; wait until the last handle is really under the pointer.
    await page.waitForFunction(() => {
        const handles = document.querySelectorAll('#world_popup_entries_list > .world_entry .drag-handle'), h = handles[handles.length - 1], r = h.getBoundingClientRect();
        return document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2) === h;
    });
    const handle = await entries.nth(3).locator('.drag-handle').boundingBox(), first = await entries.nth(0).boundingBox();
    await page.mouse.move(handle.x + handle.width / 2, handle.y + handle.height / 2);
    await page.mouse.down();
    for (let i = 1; i <= 8; i++) await page.mouse.move(handle.x + handle.width / 2, handle.y + (first.y + 4 - handle.y) * i / 8);
    await page.waitForTimeout(100);
    const mid = await page.evaluate(() => ({ line: !!document.querySelector('.wb-perf-drop-line'), ghost: !!document.querySelector('.wb-perf-drag-ghost'), placeholder: !!document.querySelector('#world_popup_entries_list .ui-sortable-placeholder') }));
    assert.deepEqual(await order(), before, 'entries must not move during the drag');
    assert.deepEqual(mid, { line: true, ghost: true, placeholder: false });
    const saveRequest = page.waitForRequest(r => r.url().endsWith('/api/worldinfo/edit'), { timeout: 10_000 });
    await page.mouse.up();
    const after = await order();
    assert.deepEqual(after, [before[3], before[0], before[1], before[2]]);
    await saveRequest;
    await page.waitForTimeout(500);
    const indices = await page.evaluate(async name => {
        const c = SillyTavern.getContext();
        const b = await (await fetch('/api/worldinfo/get', { method: 'POST', headers: c.getRequestHeaders(), body: JSON.stringify({ name }) })).json();
        return Object.values(b.entries).sort((x, y) => x.displayIndex - y.displayIndex).map(e => e.comment);
    }, BOOK);
    assert.deepEqual(indices, after);
    assert.equal(await page.locator('.wb-perf-drop-line, .wb-perf-drag-ghost').count(), 0);
    pass('world info drag: indicator only while dragging, one reorder on release, saved through the native stop handler', { before, after });
    await setModule(page, 'worldinfoDrag', false);
    const h2 = await entries.nth(0).locator('.drag-handle').boundingBox();
    await page.mouse.move(h2.x + h2.width / 2, h2.y + h2.height / 2);
    await page.mouse.down();
    // jQuery UI starts after its delay (getSortableDelay) and a few move events.
    await page.waitForTimeout(300);
    for (let i = 1; i <= 6; i++) await page.mouse.move(h2.x + h2.width / 2, h2.y + 10 * i);
    const offDrag = await page.evaluate(() => ({ ghost: !!document.querySelector('.wb-perf-drag-ghost'), sortable: !!document.querySelector('#world_popup_entries_list .ui-sortable-placeholder, #world_popup_entries_list .ui-sortable-helper') }));
    await page.mouse.up();
    assert.deepEqual(offDrag, { ghost: false, sortable: true });
    pass('world info drag off: jQuery UI sortable handles the drag (native)');

    // Master switch off: nothing of the extension is left in the page apart from its panel.
    for (const id of ['presetDryRun', 'worldinfoDrag']) await setModule(page, id, true);
    const listenersOn = await extensionListeners(page);
    assert(listenersOn.length >= 5, JSON.stringify(listenersOn));
    const status = await setModule(page, null, false);
    assert(Object.values(status).every(s => !s.active), JSON.stringify(status));
    const listenersOff = await extensionListeners(page);
    assert.deepEqual(listenersOff, []);
    const residue = await page.evaluate(async () => {
        const { PromptManager } = await import('/scripts/PromptManager.js');
        return {
            render: PromptManager.prototype.render.toString().includes('schedule(this)'),
            slideToggle: jQuery.fn.slideToggle.toString().includes('SELECTOR'),
            fetch: fetch.name === 'wbPerfFetch',
            elements: [...document.querySelectorAll('[class*="wb-perf"]')].filter(e => !e.closest('#wb-perf-settings')).length,
        };
    });
    assert.deepEqual(residue, { render: false, slideToggle: false, fetch: false, elements: 0 });
    pass('master switch off: no wb-perf listeners on document/window, patches and fetch wrapper restored, no extension elements outside the panel', { listenersOn: listenersOn.length, ...residue });
    assert.deepEqual(errors, []);
    passed = true;
} catch (error) {
    for (const p of pages) if (!p.isClosed()) await p.screenshot({ path: `${dir}/failure-${pages.indexOf(p)}.png` }).catch(() => {});
    throw error;
} finally {
    // Remove the synthetic book even when a check failed.
    const cleanup = pages.find(p => !p.isClosed());
    if (cleanup) await cleanup.evaluate(async name => {
        const c = SillyTavern.getContext();
        await fetch('/api/worldinfo/delete', { method: 'POST', headers: c.getRequestHeaders(), body: JSON.stringify({ name }) });
    }, BOOK).catch(() => {});
    fs.writeFileSync(`${dir}/verification.json`, JSON.stringify({ checkedAt: new Date().toISOString(), passed, checks, errors }, null, 2));
    await browser.close();
}
