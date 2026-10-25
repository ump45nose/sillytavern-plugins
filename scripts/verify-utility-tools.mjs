import assert from 'node:assert/strict';
import fs from 'node:fs';
import { gunzipSync } from 'node:zlib';
import { launch, session, ready, urls, artifacts, chooseLayout, openSettings, toggleRight } from './browser.mjs';
const directory = artifacts + '/utility-tools'; fs.mkdirSync(directory, { recursive: true });
const browser = await launch(), checks = [], report = { checkedAt: new Date().toISOString(), checks };
const pass = name => { checks.push(name); console.log('PASS', name); };
let page;
try {
  const testSession = await session(browser); page = testSession.page;
  let settings;
  await page.route('**/api/settings/save', async route => {
    let body = route.request().postDataBuffer(); if (route.request().headers()['content-encoding'] === 'gzip') body = gunzipSync(body);
    settings = JSON.parse(body.toString()); await route.fulfill({ json: {} });
  });
  await page.route('**/api/settings/get', async route => { const response = await route.fetch(), data = await response.json(); if (settings) data.settings = JSON.stringify(settings); await route.fulfill({ response, json: data }); });
  for (const path of ['**/api/chats/save', '**/api/chats/group/save']) await page.route(path, route => route.fulfill({ json: { result: 'ok' } }));
  await page.setViewportSize({ width: 1496, height: 817 }); await ready(page, urls.validation);
  await page.waitForFunction(() => window.workbench?.mounted && window.workbench.metrics.workbenchReadyMs);
  const role = name => page.getByRole('button', { name, exact: true }), settle = () => page.waitForTimeout(350);
  await page.evaluate(() => { workbench.host.preference({ layout: 'novel', pinnedTools: [{ id: 'wb:export', label: '记录导出' }], addons: { 'record-export': true } }); window.__utilityNative = { input: document.getElementById('send_textarea'), chat: document.getElementById('chat') }; }); await settle();
  const ensureLeft = async () => { if (await page.locator('.wb-edge-left').getAttribute('aria-expanded') === 'false') { await page.locator('.wb-edge-left').click(); await settle(); } };
  const settingsGroup = async group => { await ensureLeft(); await openSettings(page, '用户设置'); await page.getByRole('navigation', { name: '设置分组' }).getByRole('button', { name: group, exact: true }).click(); };
  const tool = id => page.locator(`.wb-composer-actions [data-wb-tool="${id}"]`);
  const exportPanel = page.getByRole('region', { name: '聊天记录分析与导出' });
  const openExport = async () => { if (await role('快进到你的回应').count()) { await role('快进到你的回应').click(); await settle(); } if (await tool('wb:export').count()) await tool('wb:export').click(); else { await role('更多工具').click(); await page.getByRole('dialog', { name: '更多工具' }).getByRole('button', { name: '记录导出', exact: true }).click(); } await page.waitForSelector('.wb-export-workspace'); };
  const waitResult = async count => { await page.waitForFunction(count => { const footer = document.querySelector('.wb-export-footer'); return footer?.querySelector('.wb-primary:not(:disabled)') && footer.querySelector('.wb-export-totals').textContent.startsWith(`${count} 层`); }, count); };
  const structure = async () => exportPanel.getByRole('button', { name: /^XML 结构/ }).click();
  const preview = async () => exportPanel.getByRole('button', { name: /^结果预览/ }).click();
  const downloadText = async () => { const downloading = page.waitForEvent('download'); await exportPanel.getByRole('button', { name: '导出', exact: true }).click(); const file = await downloading; return { text: fs.readFileSync(await file.path(), 'utf8'), name: file.suggestedFilename() }; };

  assert.equal(await page.evaluate(() => performance.getEntriesByType('resource').some(x => /addons\/record-export\/|export-worker/.test(x.name))), false);
  const arrows = await page.locator('.wb-edge-arrow').evaluateAll(nodes => nodes.map(node => ({ left: node.classList.contains('wb-edge-left'), width: node.getBoundingClientRect().width, icon: node.querySelector('svg').getBoundingClientRect().width, background: getComputedStyle(node).backgroundColor })));
  arrows.forEach(arrow => { assert.equal(arrow.width, 36); assert.equal(arrow.icon, 22); assert.equal(arrow.background, 'rgba(0, 0, 0, 0)'); });
  pass('edge controls are bare 22px chevrons with no tab; export code remains unloaded until requested');

  await settingsGroup('常用工具');
  for (const name of ['作者注释', '变量管理器', 'Token 计数', '数据银行']) await page.getByRole('checkbox', { name: `固定 ${name}`, exact: true }).check();
  await role('上移 变量管理器').click(); await settle();
  const pins = await page.evaluate(() => workbench.host.prefs().pinnedTools);
  assert.deepEqual(pins.map(t => t.label), ['记录导出', '变量管理器', '作者注释', 'Token 计数', '数据银行']);
  assert.ok(pins.find(t => t.label === '变量管理器').id.startsWith('label:tools:'));
  await page.screenshot({ path: directory + '/tool-settings-1496.png' });
  await page.evaluate(() => workbench.host.persistSettings()); await role('返回工作台').click(); await settle();
  await tool('native:menu:option_toggle_AN').click(); await page.getByRole('dialog', { name: '作者注释', exact: true }).waitFor();
  await page.locator('.wb-popover #floatingPrompt').waitFor(); await page.locator('.wb-popover').getByRole('button', { name: '关闭弹出框' }).click(); await settle();
  pass('settings select/reorder/save common tools; pinned author note uses the existing native editor');

  await page.evaluate(() => {
    const source = document.querySelector('#extensionsMenu'); const node = [...source.querySelectorAll('.list-group-item')].find(n => n.textContent.includes('变量管理器'));
    if (!node) throw new Error('Helper tool is missing');
    window.__utilityTool = { node, parent: node.parentNode, next: node.nextSibling, clicks: 0 };
    window.__utilityTool.listener = event => { event.stopImmediatePropagation(); __utilityTool.clicks++; };
    node.addEventListener('click', __utilityTool.listener, true); source.append(node);
  }); await settle();
  const variable = pins.find(t => t.label === '变量管理器'); await tool(variable.id).click();
  assert.equal(await page.evaluate(() => __utilityTool.clicks), 1);
  await page.evaluate(() => __utilityTool.node.classList.add('disabled')); await settle(); assert.equal(await tool(variable.id).isDisabled(), true);
  await page.evaluate(() => __utilityTool.node.remove()); await settle(); assert.equal(await tool(variable.id).isDisabled(), true);
  await page.evaluate(() => { const state = __utilityTool; state.node.classList.remove('disabled'); state.parent.insertBefore(state.node, state.next); state.node.removeEventListener('click', state.listener, true); delete window.__utilityTool; }); await settle();
  assert.equal(await tool(variable.id).isEnabled(), true);
  pass('anonymous helper identity survives native menu reordering; disabled/missing entries cannot invoke another tool');

  await page.setViewportSize({ width: 1024, height: 768 }); await toggleRight(page); await settle();
  await role('更多工具').click(); await page.getByRole('dialog', { name: '更多工具' }).waitFor();
  assert.ok(await page.getByRole('dialog', { name: '更多工具' }).getByRole('button', { name: '记录导出', exact: true }).count());
  await page.evaluate(id => { const node = [...workbench.host.menuItems('tools')].find(item => item.id === id).node; window.__utilityDisabled = { node, previous: node.getAttribute('aria-disabled') }; node.setAttribute('aria-disabled', 'true'); }, variable.id); await settle();
  assert.equal(await page.getByRole('dialog', { name: '更多工具' }).getByRole('button', { name: /^变量管理器/ }).isDisabled(), true);
  await page.evaluate(() => { const { node, previous } = __utilityDisabled; previous === null ? node.removeAttribute('aria-disabled') : node.setAttribute('aria-disabled', previous); delete window.__utilityDisabled; }); await settle();
  assert.equal(await page.getByRole('dialog', { name: '更多工具' }).getByRole('button', { name: '变量管理器', exact: true }).isEnabled(), true);
  const fit = await page.locator('.wb-composer-actions').evaluate(node => [...node.children].every(child => child.getBoundingClientRect().right <= node.getBoundingClientRect().right + 1)); assert.equal(fit, true);
  await page.keyboard.press('Escape'); await toggleRight(page); await page.setViewportSize({ width: 1496, height: 817 }); await settle();
  pass('narrow composer keeps a single line with accessible overflow instead of overlapping send controls');

  await page.evaluate(async () => {
    const c = SillyTavern.getContext(); window.__utilityChat = structuredClone(c.chat);
    c.chat.splice(0, c.chat.length, ...Array.from({ length: 142 }, (_, id) => ({ name: id % 2 ? '角色' : '用户', is_user: id % 2 === 0, is_system: false, send_date: Date.now(), mes: id === 141 ? '公开<think>UNFINISHED_SECRET' : `<think>SECRET_${id}</think><content location="a>b">正文${id}<after>嵌套${id}</after></content><after>结尾${id}</after>`, extra: {} })));
    await (await import('/script.js')).printMessages(); workbench.host.refresh();
  });
  const before = await page.evaluate(() => JSON.stringify(SillyTavern.getContext().chat));
  await openExport(); await waitResult(142);
  assert.equal(await page.locator('.wb-resource-rail.is-open').count(), 0);
  assert.ok(await exportPanel.getByRole('button', { name: '保留 content / after', exact: true }).count());
  await structure(); await exportPanel.getByRole('button', { name: '仅 content / after', exact: true }).click(); await waitResult(141); await preview();
  let file = await downloadText(); assert.ok(file.text.includes('正文140')); assert.ok(file.text.includes('正文0')); assert.ok(!file.text.includes('SECRET_')); assert.ok(!file.text.includes('UNFINISHED_SECRET')); assert.ok(file.name.endsWith('.txt'));
  assert.equal((file.text.match(/嵌套140/g) || []).length, 1);
  await page.screenshot({ path: directory + '/export-preview-1496.png' });
  await structure(); await exportPanel.getByRole('button', { name: '清空规则', exact: true }).click(); await exportPanel.getByRole('button', { name: '排除 think', exact: false }).first().click(); await waitResult(142);
  file = await downloadText(); assert.ok(file.text.includes('<content location="a>b">')); assert.ok(!file.text.includes('SECRET_')); assert.ok(!file.text.includes('UNFINISHED_SECRET')); assert.ok(await exportPanel.locator('.wb-export-warnings').count());
  assert.equal(await page.evaluate(() => JSON.stringify(SillyTavern.getContext().chat)), before);
  assert.equal(await page.evaluate(() => __utilityNative.input === document.getElementById('send_textarea') && __utilityNative.chat === document.getElementById('chat')), true);
  pass('right-sidebar worker analyzes all 142 raw messages, extracts nested blocks once and removes complete/unclosed think without changing chat');

  await structure();
  await exportPanel.getByRole('button', { name: '保留 content', exact: true }).click();
  await exportPanel.getByRole('button', { name: '排除 content / after', exact: true }).click(); await waitResult(141);
  file = await downloadText(); assert.ok(file.text.includes('正文140')); assert.ok(!file.text.includes('嵌套140')); assert.ok(!file.text.includes('结尾140')); assert.ok(!file.text.includes('SECRET_'));
  await exportPanel.getByRole('textbox', { name: '手动添加 XML 标签' }).fill('custom_tag'); await exportPanel.getByRole('button', { name: '添加', exact: true }).click();
  await exportPanel.getByRole('button', { name: '保留 custom_tag', exact: true }).click();
  await exportPanel.getByRole('button', { name: '移除手动标签 custom_tag', exact: true }).click(); await waitResult(141);
  assert.equal(await exportPanel.getByRole('button', { name: '保留 custom_tag', exact: true }).count(), 0);
  await page.screenshot({ path: directory + '/export-xml-rules-1496.png' });
  await exportPanel.getByRole('button', { name: '清空规则', exact: true }).click(); await waitResult(142);
  pass('retain/exclude rules operate together inside XML structure; scanned tags and manually added/removed tags share the same row controls');

  await structure(); await exportPanel.getByRole('button', { name: '仅 content / after', exact: true }).click(); await waitResult(141); await preview();
  await exportPanel.getByRole('button', { name: '范围与导出选项' }).click();
  await exportPanel.getByRole('spinbutton', { name: '导出起始楼层' }).fill('2'); await exportPanel.getByRole('spinbutton', { name: '导出结束楼层' }).fill('4'); await waitResult(3);
  await exportPanel.getByRole('checkbox', { name: '附带说话者与楼层', exact: true }).uncheck();
  await exportPanel.getByRole('checkbox', { name: '保留所选块的外层标签', exact: true }).check(); await waitResult(3);
  file = await downloadText(); assert.ok(file.text.includes('<content')); assert.ok(!file.text.includes('层 ·')); assert.ok(!file.text.includes('正文0')); assert.ok(!file.text.includes('正文4'));
  await exportPanel.getByRole('textbox', { name: '搜索导出内容' }).fill('正文3'); await waitResult(1);
  await exportPanel.getByRole('combobox', { name: '记录导出格式' }).click(); await page.getByRole('listbox', { name: '记录导出格式' }).getByRole('option', { name: 'Markdown', exact: true }).click();
  file = await downloadText(); assert.ok(file.name.endsWith('.md')); assert.ok(file.text.includes('正文3')); assert.ok(!file.text.includes('正文2'));
  await exportPanel.getByRole('textbox', { name: '搜索导出内容' }).fill('没有这个关键词'); await page.waitForFunction(() => document.querySelector('.wb-export-footer .wb-primary').disabled);
  pass('floor ranges, keyword filtering, tag retention, metadata toggle, Markdown and empty-result download guard');

  await page.evaluate(() => { window.__utilityGetContext = SillyTavern.getContext; SillyTavern.getContext = () => ({ ...__utilityGetContext(), chatId: 'WB_VERIFY_TEMPORARY_CHAT', getCurrentChatId: () => 'WB_VERIFY_TEMPORARY_CHAT' }); const c = SillyTavern.getContext(); c.chat.splice(0, c.chat.length, { name: '角色', is_user: false, mes: '<content>另一段聊天</content>', extra: {} }); workbench.host.refresh(); });
  await waitResult(1);
  assert.equal(await exportPanel.getAttribute('data-wb-filter-mode'), 'all');
  assert.equal(await exportPanel.locator('.wb-export-tag-actions button[aria-pressed=true]').count(), 0);
  await exportPanel.getByRole('button', { name: '结果预览', exact: false }).click(); assert.ok((await exportPanel.locator('.wb-export-scroll').innerText()).includes('另一段聊天')); assert.ok(!(await exportPanel.locator('.wb-export-scroll').innerText()).includes('正文3'));
  await page.evaluate(() => { const c = SillyTavern.getContext(); c.chat.splice(0, c.chat.length, ...Array.from({ length: 10000 }, (_, id) => ({ name: '角色', is_user: false, mes: `<content>后台分析 ${id}</content><think>隐藏 ${id}</think>`, extra: {} }))); workbench.host.refresh(); });
  await exportPanel.getByRole('button', { name: '重新分析聊天', exact: true }).click();
  await page.locator('#send_textarea').fill('WB_EXPORT_INPUT_DRAFT'); await exportPanel.getByRole('button', { name: '取消', exact: true }).click();
  assert.ok((await exportPanel.innerText()).includes('分析已取消')); assert.equal(await page.locator('#send_textarea').inputValue(), 'WB_EXPORT_INPUT_DRAFT');
  await page.evaluate(async () => { SillyTavern.getContext = __utilityGetContext; delete window.__utilityGetContext; const c = SillyTavern.getContext(); c.chat.splice(0, c.chat.length, ...__utilityChat); delete window.__utilityChat; await (await import('/script.js')).printMessages(); workbench.host.refresh(); });
  await toggleRight(page); await settle();
  pass('chat changes discard prior analysis; a 10,000-message scan can be cancelled while editing the original input');

  if (await page.locator('.wb-edge-left[aria-expanded=true]').count()) { await page.locator('.wb-edge-left').click(); await settle(); }
  for (const [width, height] of [[1024, 768], [2992, 1634]]) {
    await page.setViewportSize({ width, height }); await settle(); await openExport(); await waitResult(1); await settle();
    const geometry = await exportPanel.evaluate(node => ({ left: node.getBoundingClientRect().left, right: node.getBoundingClientRect().right, bottom: node.querySelector('.wb-export-footer').getBoundingClientRect().bottom, scrollHeight: node.querySelector('.wb-export-scroll').getBoundingClientRect().height, overflow: document.documentElement.scrollWidth > innerWidth }));
    assert.equal(geometry.overflow, false); assert.ok(geometry.right <= width + 1 && geometry.left >= 0 && geometry.bottom <= height + 1 && geometry.scrollHeight > 100, JSON.stringify(geometry));
    await page.screenshot({ path: directory + `/export-noval-${width}.png` }); await toggleRight(page); await settle();
  }
  await page.setViewportSize({ width: 1496, height: 817 });
  await chooseLayout(page,'RP'); await settle();
  await page.evaluate(() => workbench.host.preference({ rpTopAuto: false })); await settle();
  assert.equal(await page.locator('.wb-left.is-open,.wb-right.is-open').count(), 0);
  await openExport(); await waitResult(1);
  assert.equal(await page.evaluate(() => __utilityNative.input === document.getElementById('send_textarea') && __utilityNative.chat === document.getElementById('chat')), true);
  assert.deepEqual(await page.evaluate(() => workbench.host.prefs().pinnedTools), pins);
  file = await downloadText(); assert.ok(file.text.length > 0);
  await page.screenshot({ path: directory + '/export-rp-1496.png' }); await toggleRight(page); await settle();
  await chooseLayout(page,'Noval'); await settle();
  pass('1024 and 2992 widths keep the export footer and scrolling area usable; RP shares tools, download and original native nodes');

  await settingsGroup('加载诊断'); await page.getByRole('region', { name: '加载诊断' }).waitFor();
  const startup = await page.evaluate(() => workbenchStartup.snapshot());
  assert.ok(startup.milestones.appReadyMs > 0); assert.ok(startup.milestones.workbenchReadyMs >= startup.milestones.appReadyMs);
  assert.ok(!JSON.stringify(startup).includes('SECRET_')); assert.ok(!JSON.stringify(startup).includes('WB_EXPORT_INPUT_DRAFT'));
  await page.screenshot({ path: directory + '/startup-diagnostics-1496.png' });
  const reportDownload = page.waitForEvent('download'); await role('导出报告').click(); const downloadedReport = await reportDownload; assert.equal(JSON.parse(fs.readFileSync(await downloadedReport.path(), 'utf8')).id, startup.id);
  await role('返回工作台').click(); await page.reload({ waitUntil: 'domcontentloaded' }); await page.waitForFunction(() => window.workbench?.mounted && window.workbench.metrics.workbenchReadyMs);
  assert.deepEqual(await page.evaluate(() => workbench.host.prefs().pinnedTools), pins);
  assert.ok(await page.evaluate(() => workbenchStartup.history.length >= 2));
  report.startup = { appReadyMs: startup.milestones.appReadyMs, workbenchReadyMs: startup.milestones.workbenchReadyMs, incompleteResources: startup.incompleteResources };
  pass('browser startup diagnostics export non-content metrics; tool selections and recent navigation history survive reload');
  assert.deepEqual(testSession.errors, []); report.errors = testSession.errors; report.passed = true;
} catch (error) { report.passed = false; report.failure = error.stack; if (page) { await page.screenshot({ path: directory + '/failure.png' }).catch(() => {}); report.pageErrors = await page.evaluate(() => ({ launcher: document.querySelector('#wb-launcher')?.textContent, error: document.querySelector('.wb-error')?.textContent })).catch(() => ({})); } console.error(error); process.exitCode = 1; }
finally { fs.writeFileSync(directory + '/verification.json', JSON.stringify(report, null, 2)); await browser.close(); }
