import assert from 'node:assert/strict';
import fs from 'node:fs';
import { chromium } from 'playwright';

// Only the standalone design page. No runtime account, chat or model endpoints.
const url = 'http://192.168.31.201:33080/sillytavern/addons/';
const directory = 'artifacts/addon-design';
fs.mkdirSync(directory, { recursive: true });
const browser = await chromium.launch({
  executablePath: process.env.WB_CHROMIUM ?? '/home/yuwk/.cache/ms-playwright/chromium-1243/chrome-linux64/chrome',
  headless: true, args: ['--no-sandbox', '--disable-dev-shm-usage', '--no-proxy-server'],
});
const context = await browser.newContext({ viewport: { width: 1496, height: 817 } });
const page = await context.newPage(), errors = [], requests = [], checks = [];
page.on('pageerror', error => errors.push(error.message));
page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
page.on('request', request => requests.push(request.url()));
page.on('response', response => { if (response.status() >= 400) errors.push(`${response.status()} ${response.url()}`); });
const pass = name => { checks.push(name); console.log('PASS', name); };
const click = action => page.locator(`[data-action="${action}"]:visible`).first().click();
const settle = () => page.waitForTimeout(250);
const panel = () => page.locator('#panel-content');
const deep = () => page.locator('#deep-page');
const field = name => page.locator(`[data-field="${name}"]:visible`).first();
const reset = async query => { await page.goto(url + (query || '')); await settle(); };
try {
  const response = await page.goto(url); await settle();
  assert.match(response.headers()['cache-control'], /no-store/);
  const geometry = await page.evaluate(() => {
    const box = selector => { const r = document.querySelector(selector).getBoundingClientRect(); return { x: r.x, width: r.width, height: r.height }; };
    return { nav: box('.navigation'), work: box('.workarea'), header: box('.topbar'), body: document.body.scrollWidth, viewport: innerWidth };
  });
  assert.equal(geometry.nav.width, 260); assert.equal(geometry.work.width, 460); assert.equal(geometry.header.height, 74); assert.equal(geometry.body, geometry.viewport);
  await page.screenshot({ path: `${directory}/outline-workspace-1496.png` });
  pass('LAN entry, no-store and real 1496×817 geometry');

  assert.equal(await page.getByText('工作台设置 · 沿用当前组件', {exact:true}).count(),0);
  assert.equal(await page.locator('#nav-settings').evaluate(el=>el.inert),true);
  assert.equal(await page.locator('#nav-settings-actions button').count(),2);
  const expandedTreeHeight=await page.locator('#nav-tree').evaluate(el=>el.getBoundingClientRect().height);
  await click('fold-settings');await page.waitForTimeout(100);
  const animatedSettingsHeight=await page.locator('#nav-settings').evaluate(el=>el.getBoundingClientRect().height);
  await settle();
  assert.ok(animatedSettingsHeight>1&&animatedSettingsHeight<await page.locator('#nav-settings').evaluate(el=>el.getBoundingClientRect().height));
  assert.equal(await page.locator('#nav-settings').evaluate(el=>el.inert),false);
  assert.ok(await page.locator('#nav-tree').evaluate(el=>el.getBoundingClientRect().height)<expandedTreeHeight-100);
  await click('fold-settings');await settle();
  await page.locator('#nav-settings-actions [data-action="settings"]').click();assert.equal(await deep().isVisible(),true);await click('close-deep');
  pass('outline frees settings space; two controls expand with motion or open the settings page');

  const leftHeight = await page.locator('#nav-outline').evaluate(el => el.getBoundingClientRect().height);
  await click('fold-tree'); await page.waitForTimeout(100);
  const middleHeight = await page.locator('#nav-outline').evaluate(el => el.getBoundingClientRect().height);
  assert.ok(middleHeight > 1 && middleHeight < leftHeight);
  await settle();
  assert.ok(await page.locator('#nav-outline').evaluate(el => el.getBoundingClientRect().height) < 2);
  assert.equal(await page.locator('#nav-settings').evaluate(el=>el.inert),false);
  assert.equal(await page.locator('#nav-settings-actions').isVisible(),false);
  await page.screenshot({ path: `${directory}/outline-left-collapsed-1496.png` });
  await click('fold-tree'); await settle();
  const branch = page.locator('#nav-tree [data-action="branch"][data-id="chapter1"]');
  const branchGroup = page.locator('#nav-tree [data-branch-container="chapter1"]');
  const branchHeight = await branchGroup.evaluate(el => el.getBoundingClientRect().height);
  await branch.click(); await page.waitForTimeout(100);
  const branchMiddle = await branchGroup.evaluate(el => el.getBoundingClientRect().height);
  assert.ok(branchMiddle > 1 && branchMiddle < branchHeight); await settle();
  assert.ok(await branchGroup.evaluate(el => el.getBoundingClientRect().height) < 2);
  await branch.click(); await settle();
  const brief = page.locator('#nav-tree [data-brief-container="promise"]');
  assert.equal(await brief.locator('.node-brief-card').isVisible(), true);
  await page.locator('#nav-tree [data-action="node-brief"][data-id="promise"]').click(); await settle();
  assert.ok(await brief.evaluate(el => el.getBoundingClientRect().height) < 2);
  await page.locator('#nav-tree [data-action="node-brief"][data-id="promise"]').click(); await settle();
  await page.screenshot({ path: `${directory}/outline-left-expanded-1496.png` });
  pass('left outline releases collapsed height, branch animates through intermediate frames and node content expands inline');

  await click('deep-outline'); await settle();
  await page.screenshot({ path: `${directory}/outline-editor-1496.png` });
  await field('node-content').fill('## 验证标题\n\n**林间**\n\n<script>window.prototypeEscaped=false</script>');
  assert.equal(await page.locator('#live-preview h3').textContent(), '验证标题');
  assert.equal(await page.locator('#live-preview strong').textContent(), '林间');
  assert.equal(await page.locator('#live-preview script').count(), 0);
  await field('tree-search').fill('灯塔');
  assert.equal(await page.locator('#deep-tree [role="treeitem"]').count(), 4);
  await field('tree-search').fill('拆开信封');
  assert.equal(await page.locator('#deep-tree [role="treeitem"]').count(), 2);
  await field('tree-search').fill('');
  await click('toggle-preview'); assert.equal(await page.locator('.preview-area').isVisible(), false);
  await click('toggle-preview'); assert.equal(await page.locator('.preview-area').isVisible(), true);
  pass('Markdown editing, escaped content, tree search and preview folding');

  await click('duplicate-node');
  assert.match(await field('node-title').inputValue(), /副本/);
  await click('delete-node'); await click('confirm-delete');
  assert.equal(await page.locator('#deep-tree [role="treeitem"]').count(), 6);
  await page.locator('#deep-tree [data-node="letter"] button.node-choice').click();
  await page.locator('#deep-tree [data-node="letter"] .node-choice').press('Alt+ArrowLeft');
  assert.equal(await page.locator('#deep-tree [data-node="letter"]').getAttribute('aria-level'), '1');
  await page.locator('#deep-tree [data-node="letter"]').dragTo(page.locator('#deep-tree [data-node="chapter1"]'));
  const treeOrder = await page.locator('#deep-tree [role="treeitem"]').evaluateAll(nodes => nodes.map(n => n.dataset.node));
  assert.equal(treeOrder[0], 'letter');
  pass('duplicate/delete, keyboard hierarchy and pointer drag ordering');

  await click('import-export');
  const downloadPromise = page.waitForEvent('download'); await click('export-json');
  const exported = JSON.parse(fs.readFileSync(await (await downloadPromise).path(), 'utf8'));
  assert.equal(exported.nodes.length, 6); assert.equal(exported.nodes.find(n => n.id === 'promise').rounds, 2);
  await field('import-text').fill(JSON.stringify({ nodes: [{ id: 'cycle', parent: 'cycle', title: '循环', content: '正文' }] }));
  await click('preview-import'); assert.match(await page.locator('#import-error').textContent(), /循环/);
  assert.equal(await page.locator('[data-action="confirm-import"]').isDisabled(), true);
  await field('import-text').fill('# 新章节\n\n背景\n\n## 新场景\n\n场景内容');
  await click('preview-import'); assert.match(await page.locator('#import-preview').textContent(), /2 个节点/);
  await field('import-mode').selectOption('replace'); await click('confirm-import');
  assert.equal(await page.locator('#deep-tree [role="treeitem"]').count(), 2);
  assert.equal(await field('node-title').inputValue(), '新章节');
  pass('JSON export, invalid graph rejection and Markdown preview before replacement');

  await reset(); await click('fold-settings'); await settle(); await click('shortcuts');
  const binding = page.getByRole('textbox', { name: '打开完整大纲快捷键', exact: true });
  await binding.press('Control+R'); assert.match(await page.locator('#shortcut-error').textContent(), /冲突/);
  await binding.press('Control+Alt+O'); assert.equal(await binding.inputValue(), 'Ctrl+Alt+O');
  await click('close-dialog'); await page.keyboard.press('Control+Alt+O');
  assert.equal(await deep().isVisible(), true);
  await click('close-deep');
  await page.locator('#draft').fill('前文尾文');
  await page.locator('#draft').evaluate(el => el.setSelectionRange(2, 2));
  await page.keyboard.press('Control+Shift+I');
  assert.match(await page.locator('#draft').inputValue(), /^前文## 场景目标/);
  assert.match(await page.locator('#draft').inputValue(), /尾文$/);
  await panel().locator('[data-action="outline-tab"][data-value="writing"]').click();
  await field('insertion').selectOption('replace');
  await click('quick-insert'); assert.match(await page.locator('#draft').inputValue(), /^## 场景目标/);
  assert.doesNotMatch(await page.locator('#draft').inputValue(), /尾文$/);
  await field('send-after').check(); await click('quick-insert');
  await page.waitForTimeout(800); assert.equal(await page.locator('#messages .message').count(), 5);
  pass('custom shortcut conflict checks, caret insertion, replacement and optional send');

  await reset(); await panel().locator('[data-action="outline-tab"][data-value="writing"]').click();
  await click('start-writing'); await click('close-right'); await settle();
  assert.equal(await page.getByRole('button', { name: '暂停写作', exact: true }).isVisible(), true);
  await page.getByRole('button', { name: '暂停写作', exact: true }).click();
  await page.waitForTimeout(2400);
  assert.equal(await page.getByRole('button', { name: '继续写作', exact: true }).isVisible(), true);
  const countBefore = await page.locator('#messages .message').count();
  await page.waitForTimeout(700); assert.equal(await page.locator('#messages .message').count(), countBefore);
  await page.getByRole('button', { name: '继续写作', exact: true }).click();
  await page.getByRole('button', { name: '停止写作', exact: true }).click();
  await page.waitForTimeout(2400); assert.equal(await page.locator('#messages .message').count(), countBefore);
  pass('background writing, pause after current round, resume and cancel pending work');

  await reset(); await panel().locator('[data-action="outline-tab"][data-value="writing"]').click();
  await click('start-writing'); await page.waitForTimeout(100); await page.locator('#draft').fill('用户介入');
  await page.waitForTimeout(2400); assert.equal(await page.getByRole('button', { name: '继续写作', exact: true }).first().isVisible(), true);
  await click('stop-writing');
  await reset(); await panel().locator('[data-action="outline-tab"][data-value="writing"]').click();
  await click('start-writing'); await page.waitForTimeout(9100);
  assert.match(await panel().textContent(), /本次大纲已写完/);
  assert.match(await page.locator('#outline-count').textContent(), /4 \/ 4/);
  pass('manual intervention pauses; multiple leaf nodes and rounds complete in order');

  await reset('?panel=image'); await click('deep-image'); await settle();
  const connectionRows = await page.locator('.config-card').first().locator('.four-columns input').evaluateAll(elements => elements.map(el => Math.round(el.getBoundingClientRect().top)));
  assert.equal(new Set(connectionRows).size, 1);
  await field('config-width').fill('768');
  await page.locator('[data-action="backend"][data-value="ComfyUI"]').click();
  assert.equal(await field('workflow').isVisible(), true);
  await page.locator('[data-action="backend"][data-value="OpenAI 兼容"]').click();
  assert.equal(await field('config-width').inputValue(), '768');
  await settle();
  await page.screenshot({ path: `${directory}/image-config-1496.png` });
  for (const backend of ['Gemini', 'NovelAI', 'A1111', 'ComfyUI']) {
    await page.locator(`[data-action="backend"][data-value="${backend}"]`).click();
    assert.equal(await field('config-name').isVisible(), true);
  }
  await click('save-config');
  await settle();
  await page.screenshot({ path: `${directory}/image-workspace-1496.png` });
  pass('five backend layouts, compact connection row, four parameter columns and retained preview edits');

  await click('rewrite'); await page.waitForTimeout(1250);
  assert.match(await field('positive').inputValue(), /soft lighting/);
  await click('generate-direct'); await click('close-right'); await page.waitForTimeout(1850);
  assert.equal(await page.locator('#task-badges .task-badge').count(), 0);
  if(await page.locator('[data-action="panel-image"]:visible').count()===0){await click('toggle-right');await settle();}
  await click('panel-image');
  assert.equal(await page.locator('.result-image').count(), 1);
  await click('insert-image'); assert.equal(await page.locator('[data-message="m3"] .message-media').count(), 1);
  await click('replace-image'); assert.equal(await page.locator('[data-message="m3"] .message-media').count(), 1);
  await page.locator('[data-message="m3"] [data-action="remove-attachment"]').click();
  assert.equal(await page.locator('#messages .message-media').count(), 0);
  await page.locator('.result-image').dragTo(page.locator('[data-message="m1"]'));
  assert.equal(await page.locator('[data-message="m1"] .message-media').count(), 1);
  await page.screenshot({ path: `${directory}/image-attachment-1496.png` });
  pass('rewrite and background image job; native-shaped attachment insertion, replace/remove and pointer drag');

  await reset('?panel=image');
  await panel().locator('[data-action="image-tab"][data-value="automatic"]').click();
  await field('image-every').fill('1'); await field('image-every').blur();
  await field('image-delivery').selectOption('workspace'); await field('auto-image').check();
  await click('simulate-round'); await click('close-right'); await page.waitForTimeout(3000);
  assert.equal(await page.locator('.message-media').count(), 0);
  if(await page.locator('[data-action="panel-image"]:visible').count()===0){await click('toggle-right');await settle();}
  await click('panel-image'); await panel().locator('[data-action="image-tab"][data-value="results"]').click();
  assert.equal(await page.locator('.result-image').count(), 1);
  await panel().locator('[data-action="image-tab"][data-value="automatic"]').click();
  await field('image-delivery').selectOption('insert'); await click('simulate-round'); await page.waitForTimeout(3000);
  assert.equal(await page.locator('.message-media').count(), 1);
  pass('automatic reply count and both image delivery choices');

  await reset('?panel=image'); await click('deep-image');
  await page.locator('[data-action="config-tab"][data-value="rewrite"]').click();
  await field('simulate-failure').check(); await click('save-config');
  await click('generate-direct'); await page.waitForTimeout(1800);
  assert.match(await page.locator('.error-note').textContent(), /目标楼层已保留/);
  assert.match(await field('positive').inputValue(), /silver hair/);
  await click('deep-image'); await field('simulate-failure').uncheck(); await click('save-config');
  await click('generate-direct'); await click('cancel-image'); await page.waitForTimeout(1800);
  assert.equal(await page.locator('.result-image').count(), 0);
  pass('error recovery retains prompt; canceled image completion never appears');

  await reset(); await panel().locator('[data-action="outline-tab"][data-value="writing"]').click(); await click('start-writing');
  await click('settings'); await field('enable-outline').uncheck();
  await click('save-config'); await settle();
  assert.equal(await page.locator('#outline-entry').isVisible(), false);
  assert.equal(await page.locator('#task-badges .task-badge').count(), 0);
  await page.screenshot({ path: `${directory}/disabled-outline-1496.png` });
  pass('disabling add-on hides entry and stops its background runtime');

  await reset(); await click('toggle-right');
  const transition = await page.locator('.workarea').evaluate(el => getComputedStyle(el).transitionDuration);
  assert.match(transition, /0\.22s/); await settle();
  await click('mode-menu'); await click('mode-rp');
  assert.equal(await page.locator('.edge-left').getAttribute('aria-expanded'), 'false');
  assert.equal(await page.locator('.edge-right').getAttribute('aria-expanded'), 'false');
  if(await page.locator('[data-action="panel-image"]:visible').count()===0){await click('toggle-right');await settle();}
  await click('panel-image'); await settle();
  await page.screenshot({ path: `${directory}/rp-workspace-1496.png` });
  await page.emulateMedia({ reducedMotion: 'reduce' });
  assert.equal(await page.locator('.workarea').evaluate(el => parseFloat(getComputedStyle(el).transitionDuration) < .01), true);
  await page.emulateMedia({ reducedMotion: 'no-preference' });
  pass('visible drawer motion, reduced motion and shared RP workspace with default hidden sidebars');

  for (const [width, height] of [[1024,768],[1366,768],[1496,817],[1920,1080],[2992,1634]]) {
    await page.setViewportSize({ width, height });
    for (const query of ['', '?view=outline', '?view=image', '?view=settings', '?panel=image&mode=rp']) {
      await reset(query);
      assert.equal(await page.evaluate(() => document.body.scrollWidth <= innerWidth), true, `${width} ${query} horizontal overflow`);
      const clip = await page.locator('#deep-page:not([hidden]) .deep-top button, #deep-page:not([hidden]) .deep-bottom button, .edge, .top-actions button').evaluateAll(elements => elements.filter(el => {
        const r=el.getBoundingClientRect();return r.width>0&&(r.left<-.5||r.right>innerWidth+.5||r.top<-.5||r.bottom>innerHeight+.5);
      }).map(el => el.getAttribute('aria-label') || el.textContent));
      assert.deepEqual(clip, [], `${width} ${query} clipped controls`);
      if(width===1024&&query==='?view=outline')await page.screenshot({path:`${directory}/outline-editor-1024.png`});
      if(width===2992&&query==='?view=image')await page.screenshot({path:`${directory}/image-config-2992.png`});
    }
  }
  pass('five real viewport sizes, 25 page states, reachable headers/footers and no body overflow');
  assert.deepEqual(errors, []);
  assert.equal(requests.some(request => !request.startsWith('http://192.168.31.201:33080/')), false);
  assert.equal(requests.some(request => request.includes('/api/')), false);
  pass('zero page/resource errors, external requests or runtime API access');
  fs.writeFileSync(`${directory}/verification.json`, JSON.stringify({ checkedAt: new Date().toISOString(), url, checks, errors }, null, 2));
} finally { await browser.close(); }
