import assert from 'node:assert/strict';
import fs from 'node:fs';
import { gunzipSync } from 'node:zlib';
import { launch, session, ready, urls, artifacts, openSettings, toggleRight } from './browser.mjs';
const directory = artifacts + '/addons'; fs.mkdirSync(directory, { recursive: true });
const browser = await launch(), checks = [], report = { checkedAt: new Date().toISOString(), checks };
const pass = name => { checks.push(name); console.log('PASS', name); };
let page;
async function protectedSession() {
  const test = await session(browser); let saved;
  await test.page.route('**/api/settings/save', async route => {
    let body = route.request().postDataBuffer(); if (route.request().headers()['content-encoding'] === 'gzip') body = gunzipSync(body);
    saved = JSON.parse(body.toString()); await route.fulfill({ json: {} });
  });
  await test.page.route('**/api/settings/get', async route => {
    const response = await route.fetch(), data = await response.json(), settings = saved || JSON.parse(data.settings);
    settings.extension_settings.workbench ??= {};
    settings.extension_settings.workbench.layout = 'novel';
    settings.extension_settings.workbench.pinnedTools = [{ id: 'wb:export', label: '记录导出' }];
    settings.extension_settings.workbench.addons ??= { 'record-export': true };
    data.settings = JSON.stringify(settings); await route.fulfill({ response, json: data });
  });
  for (const endpoint of ['**/api/chats/save', '**/api/chats/group/save']) await test.page.route(endpoint, route => route.fulfill({ json: { result: 'ok' } }));
  await test.context.addInitScript(() => {
    window.__addonWorkers = { created: 0, terminated: 0, active: 0 };
    const NativeWorker = window.Worker;
    window.Worker = class extends NativeWorker {
      constructor(url, options) {
        super(url, options); this.addonTracked = String(url).includes('/addons/record-export/'); this.addonTerminated = false;
        if (this.addonTracked) { __addonWorkers.created++; __addonWorkers.active++; }
      }
      terminate() {
        if (this.addonTracked && !this.addonTerminated) { __addonWorkers.terminated++; __addonWorkers.active--; this.addonTerminated = true; }
        return super.terminate();
      }
    };
  });
  return test;
}
const hasExportRequests = requests => requests.some(url => url.includes('/addons/record-export/'));
try {
  const test = await protectedSession(); page = test.page;
  const requests = []; page.on('request', request => requests.push(request.url()));
  await page.setViewportSize({ width: 1496, height: 817 }); await ready(page, urls.validation);
  await page.waitForFunction(() => window.workbench?.mounted && window.workbench.metrics.workbenchReadyMs);
  const button = name => page.getByRole('button', { name, exact: true }), settle = () => page.waitForTimeout(350);
  const pins = await page.evaluate(() => workbench.host.prefs().pinnedTools);
  let original = await page.evaluate(() => { window.__addonNative = { input: document.getElementById('send_textarea'), chat: document.getElementById('chat') }; return JSON.stringify(SillyTavern.getContext().chat); });
  assert.equal(hasExportRequests(requests), false);
  assert.equal(await page.locator('link[data-wb-addon-style]').count(), 0);
  assert.equal(await page.evaluate(() => __addonWorkers.created), 0);
  pass('startup loads no add-on manifest, export module, stylesheet or worker');

  if (await page.locator('.wb-edge-left').getAttribute('aria-expanded') === 'false') { await page.locator('.wb-edge-left').click(); await settle(); }
  await openSettings(page, '扩展');
  await page.getByRole('navigation', { name: '设置分组' }).getByRole('button', { name: '工作台附加功能', exact: true }).click();
  await page.getByRole('region', { name: '工作台附加功能' }).waitFor();
  assert.equal(hasExportRequests(requests), false);
  await page.screenshot({ path: directory + '/addon-settings-1496.png' });
  { const toggle = page.getByRole('switch', { name: '启用记录导出', exact: true }); if ((await toggle.getAttribute('aria-checked')) === 'true') await toggle.click(); assert.equal(await toggle.getAttribute('aria-checked'), 'false'); }
  await page.evaluate(() => workbench.host.persistSettings()); await button('返回工作台').click(); await settle();
  assert.equal(await page.locator('[data-wb-tool="wb:export"]').count(), 0);
  await toggleRight(page); await settle();
  assert.equal(await page.locator('.wb-panel-tabs').getByRole('button', { name: '记录导出', exact: true }).count(), 0);
  await page.reload({ waitUntil: 'domcontentloaded' }); await page.waitForFunction(() => window.workbench?.mounted);
  assert.equal(await page.evaluate(() => workbench.host.prefs().addons['record-export']), false);
  assert.deepEqual(await page.evaluate(() => workbench.host.prefs().pinnedTools), pins);
  assert.equal(hasExportRequests(requests), false);
  original = await page.evaluate(() => { window.__addonNative = { input: document.getElementById("send_textarea"), chat: document.getElementById("chat") }; return JSON.stringify(SillyTavern.getContext().chat); });
  pass('management stays light; disabling persists across reload and hides both entries while retaining toolbar preferences');

  await page.evaluate(() => workbench.host.preference({ addons: { 'record-export': true } })); await settle();
  assert.ok(await page.locator('[data-wb-tool="wb:export"]').count());
  let release, requested = false;
  const gate = new Promise(resolve => { release = resolve; });
  await page.route('**/addons/record-export/manifest.json', async route => { requested = true; await gate; await route.fallback(); });
  await page.locator('[data-wb-tool="wb:export"]').click();
  while (!requested) await page.waitForTimeout(20);
  await toggleRight(page); await settle(); release();
  await page.waitForFunction(() => performance.getEntriesByType('resource').some(entry => /addons\/record-export\/index\.js/.test(entry.name)));
  await settle(); assert.equal(await page.locator('link[data-wb-addon-style]').count(), 0);
  assert.equal(await page.evaluate(() => __addonWorkers.active), 0);
  pass('closing during initial module loading never mounts a stale workspace or starts analysis');

  await page.locator('[data-wb-tool="wb:export"]').click();
  await page.getByRole('region', { name: '聊天记录分析与导出' }).waitFor();
  await page.waitForFunction(() => !!document.querySelector('.wb-export-footer .wb-primary:not(:disabled)'));
  assert.equal(await page.locator('link[data-wb-addon-style="record-export"]').count(), 1);
  assert.equal(await page.evaluate(() => __addonWorkers.active), 1);
  const download = page.waitForEvent('download'); await page.locator('.wb-export-footer').getByRole('button', { name: '导出', exact: true }).click();
  assert.ok(fs.readFileSync(await (await download).path(), 'utf8').length > 0);
  const moduleRequests = requests.filter(url => /addons\/record-export\/index\.js/.test(url)).length;
  await toggleRight(page); await settle();
  assert.equal(await page.locator('link[data-wb-addon-style]').count(), 0);
  assert.equal(await page.evaluate(() => __addonWorkers.active), 0);
  await page.locator('[data-wb-tool="wb:export"]').click();
  await page.waitForFunction(() => __addonWorkers.active === 1);
  assert.equal(requests.filter(url => /addons\/record-export\/index\.js/.test(url)).length, moduleRequests);
  await page.evaluate(() => workbench.host.preference({ addons: { 'record-export': false } })); await settle();
  assert.equal(await page.evaluate(() => __addonWorkers.active), 0);
  assert.equal(await page.locator('link[data-wb-addon-style]').count(), 0);
  assert.equal(await page.locator('.wb-right.is-open').count(), 0);
  assert.equal(await page.evaluate(() => __addonNative.input === document.getElementById('send_textarea') && __addonNative.chat === document.getElementById('chat')), true);
  assert.equal(await page.evaluate(() => JSON.stringify(SillyTavern.getContext().chat)), original);
  pass('opening loads isolated assets and exports; close/disable terminate the worker and remove CSS, reopening reuses the module');
  assert.deepEqual(test.errors, []);

  const failureTest = await protectedSession(); page = failureTest.page; let fail = true;
  await page.route('**/addons/record-export/manifest.json', async route => fail ? route.fulfill({ status: 404, contentType: 'application/json', body: '{}' }) : route.fallback());
  await ready(page, urls.validation); await page.waitForFunction(() => window.workbench?.mounted);
  await page.locator('[data-wb-tool="wb:export"]').click(); await page.getByRole('region', { name: '附加插件加载失败' }).waitFor();
  assert.equal(await page.evaluate(() => workbench.mounted && __addonWorkers.active === 0), true);
  await page.locator('#send_textarea').fill('WB_ADDON_FAILURE_DRAFT');
  await page.screenshot({ path: directory + '/addon-missing-files.png' });
  fail = false; await page.getByRole('button', { name: '重新载入', exact: true }).click();
  await page.getByRole('region', { name: '聊天记录分析与导出' }).waitFor();
  assert.equal(await page.locator('#send_textarea').inputValue(), 'WB_ADDON_FAILURE_DRAFT');
  await toggleRight(page); await page.waitForFunction(() => __addonWorkers.active === 0);
  assert.deepEqual(failureTest.errors, []);
  pass('missing add-on files fail only in the right workspace; retry succeeds without losing the native input draft');
  const versionTest = await protectedSession(); page = versionTest.page; let incompatible = true, missingEntry = true;
  const entryRequests = []; page.on('request', request => { if (/addons\/record-export\/index\.js/.test(request.url())) entryRequests.push(request.url()); });
  await page.route('**/addons/record-export/manifest.json', async route => {
    if (!incompatible) return route.fallback();
    const response = await route.fetch(), manifest = await response.json(); manifest.apiVersion = 2;
    await route.fulfill({ response, json: manifest });
  });
  await page.route('**/addons/record-export/index.js?*', async route => missingEntry ? route.fulfill({ status: 404, contentType: 'text/javascript', body: '' }) : route.fallback());
  await ready(page, urls.validation); await page.waitForFunction(() => window.workbench?.mounted);
  await page.locator('[data-wb-tool="wb:export"]').click();
  await page.getByRole('region', { name: '附加插件加载失败' }).waitFor();
  assert.ok((await page.locator('.wb-addon-message').innerText()).includes('版本不兼容'));
  assert.equal(entryRequests.length, 0); assert.equal(await page.evaluate(() => __addonWorkers.active), 0);
  incompatible = false; await page.getByRole('button', { name: '重新载入', exact: true }).click();
  await page.waitForFunction(() => document.querySelector('.wb-addon-message')?.textContent.includes('Failed to fetch dynamically imported module'));
  assert.equal(await page.evaluate(() => workbench.mounted && __addonWorkers.active === 0), true);
  missingEntry = false; await page.getByRole('button', { name: '重新载入', exact: true }).click();
  await page.getByRole('region', { name: '聊天记录分析与导出' }).waitFor();
  assert.ok(entryRequests.at(-1).includes('retry=2'));
  await toggleRight(page); await page.waitForFunction(() => __addonWorkers.active === 0);
  assert.deepEqual(versionTest.errors, []);
  pass('incompatible API is rejected before import; a failed module request retries with a fresh URL and leaves the workbench usable');
  report.passed = true; report.errors = [...test.errors, ...failureTest.errors, ...versionTest.errors];
} catch (error) {
  report.passed = false; report.failure = error.stack; process.exitCode = 1; console.error(error);
  if (page) await page.screenshot({ path: directory + '/failure.png' }).catch(() => {});
} finally { fs.writeFileSync(directory + '/verification.json', JSON.stringify(report, null, 2)); await browser.close(); }
