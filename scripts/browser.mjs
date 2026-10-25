import { chromium } from 'playwright';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

export const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
export const artifacts = path.join(root, 'artifacts');
fs.mkdirSync(artifacts, { recursive: true });
const env = Object.fromEntries(fs.readFileSync(path.join(root, '.env'), 'utf8').split('\n')
    .filter(line => line.includes('=') && !line.startsWith('#')).map(line => [line.slice(0, line.indexOf('=')), line.slice(line.indexOf('=') + 1)]));
export const credentials = { username: env.WB_USERNAME, password: env.WB_PASSWORD };
// WB_PORT_OFFSET lets a second checkout run its own local instances beside the default ones.
const offset = Number(process.env.WB_PORT_OFFSET ?? env.WB_PORT_OFFSET ?? 0);
export const ports = { baseline: 32011 + offset, validation: 32012 + offset, mock: 32013 + offset, visual: 32014 + offset };
// A wildcard bind address is not a destination; local scripts reach those instances over loopback.
const host = env.WB_BIND_ADDRESS === '0.0.0.0' ? '127.0.0.1' : env.WB_BIND_ADDRESS;
export const urls = {
    baseline: `http://${host}:${ports.baseline}`,
    validation: `http://${host}:${ports.validation}`,
    mock: `http://127.0.0.1:${ports.mock}`,
    // Disposable, reseeded instance for screenshot baselines (local runtime only).
    visual: `http://${host}:${ports.visual}`,
};
// The URL the tavern server uses to reach the deterministic provider (Docker DNS by default).
export const mockApi = env.WB_MOCK_API || 'http://mock-model:4010/v1';

export function resetSyntheticChats() {
    // Only the explicitly named synthetic fixture in these isolated data roots.
    // Never accept a caller-supplied path and never touch production volumes.
    for (const name of ['baseline', 'validation']) {
        const user = path.join(root, 'runtime', name, 'data/default-user');
        fs.rmSync(path.join(user, 'chats/WorkbenchFixture'), { recursive: true, force: true });
        const settingsPath = path.join(user, 'settings.json');
        const settings = JSON.parse(fs.readFileSync(settingsPath, 'utf8'));
        settings.active_character = null;
        settings.active_group = null;
        settings.firstRun = false;
        settings.world_info_settings.world_info.globalSelect = [];
        fs.writeFileSync(settingsPath, JSON.stringify(settings, null, 2));
    }
}

export async function launch() {
    const hostChromium = '/home/yuwk/.cache/ms-playwright/chromium-1243/chrome-linux64/chrome';
    // Fall back to Playwright's own download (npx playwright install chromium) on other machines.
    const executablePath = process.env.WB_CHROMIUM ?? (fs.existsSync(hostChromium) ? hostChromium : undefined);
    return chromium.launch({ executablePath, headless: true, args: ['--no-sandbox', '--disable-dev-shm-usage', '--no-proxy-server'] });
}

// The real database plug-in (龙血玄黄·数据库), when installed, auto-fills tables after every reply and injects
// prompts, so a session serves it as an empty module unless asked; verify:database stands in for it with seedDatabase.
// Serving the file (not editing settings) holds even where a check routes /api/settings itself.
export async function session(browser, { mobile = false, helper = true, probe = true, database = false, timings = true, recordVideo } = {}) {
    const context = await browser.newContext({
        httpCredentials: credentials,
        viewport: mobile ? { width: 390, height: 844 } : { width: 1440, height: 900 },
        isMobile: mobile, hasTouch: mobile,
        recordVideo,
    });
    // The local instances link workbench-probe to the main checkout; serve this checkout's build so a
    // worktree verifies its own code against the shared instances.
    const extension = path.join(root, 'extension');
    if (probe) await context.route('**/scripts/extensions/third-party/workbench-probe/**', route => {
        const file = path.join(extension, decodeURIComponent(new URL(route.request().url()).pathname.split('/workbench-probe/')[1]));
        return file.startsWith(extension + path.sep) && fs.existsSync(file) ? route.fulfill({ path: file }) : route.fulfill({ status: 404, body: '' });
    });
    if (!database) await context.route('**/scripts/extensions/third-party/shujuku/index.js', route => route.fulfill({ contentType: 'text/javascript', body: '' }));
    if (!helper || !probe) {
        // These flags are session-only test overrides; never persist them to the test account.
        await context.route('**/api/settings/save', route => route.fulfill({ json: {} }));
        await context.route('**/api/settings/get', async route => {
            const response = await route.fetch();
            const data = await response.json();
            const settings = JSON.parse(data.settings);
            if (!helper) settings.extension_settings.disabledExtensions.push('third-party/JS-Slash-Runner');
            if (!probe) settings.extension_settings.disabledExtensions.push('third-party/workbench-probe');
            data.settings = JSON.stringify(settings);
            await route.fulfill({ response, json: data });
        });
    }
    if (timings) await context.addInitScript(() => {
        window.baselineMetrics = { navigationStart: performance.timeOrigin };
        const timer = setInterval(() => {
            let context;
            try { context = window.SillyTavern?.getContext?.(); }
            catch { return; } // ES module exports can exist before cyclic imports finish.
            if (!context?.eventSource) return;
            clearInterval(timer);
            window.baselineMetrics.contextAvailableMs = performance.now();
            context.eventSource.on(context.eventTypes.APP_INITIALIZED, () => { window.baselineMetrics.appInitializedMs = performance.now(); });
            context.eventSource.on(context.eventTypes.APP_READY, () => { window.baselineMetrics.appReadyMs = performance.now(); });
        }, 5);
    });
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    return { context, page, errors };
}

export async function ready(page, url, { probe = false } = {}) {
    await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 60_000 });
    await page.waitForFunction(() => Number.isFinite(window.baselineMetrics?.appReadyMs), null, { timeout: 90_000 });
    if (probe) await page.waitForFunction(() => window.workbenchProbe?.mounted, null, { timeout: 10_000 });
}

/** Temporary motion checks must not change the shared validation account. */
export async function withMotionPreference(page, verify) {
    const original = await page.evaluate(() => ({
        setting: SillyTavern.getContext().powerUserSettings.reduced_motion,
        os: matchMedia('(prefers-reduced-motion: reduce)').matches,
    }));
    const protect = async route => {
        const body = route.request().postDataJSON();
        if (body?.power_user) body.power_user.reduced_motion = original.setting;
        await route.continue({ postData: JSON.stringify(body) });
    };
    await page.route('**/api/settings/save', protect);
    try {
        return await verify();
    } finally {
        await page.emulateMedia({ reducedMotion: 'no-preference' });
        await page.evaluate(value => jQuery('#reduced_motion').prop('checked', value).trigger('input'), original.setting);
        await page.unroute('**/api/settings/save', protect);
        await page.evaluate(async () => (await import('/script.js')).saveSettings());
        if (original.os) await page.emulateMedia({ reducedMotion: 'reduce' });
    }
}

/** ST persists the OS preference; emulate it only inside a protected session. */
export async function withReducedMotion(page, verify) {
    return withMotionPreference(page, async () => {
        await page.emulateMedia({ reducedMotion: 'reduce' });
        // ST reads the OS preference only on init/input, not on a media-query change.
        await page.evaluate(() => jQuery('#reduced_motion').prop('checked', true).trigger('input'));
        await page.waitForFunction(() => document.body.classList.contains('reduced-motion'));
        return verify();
    });
}

export async function createCharacter(page) {
    return page.evaluate(async () => {
        const context = SillyTavern.getContext();
        const name = 'WorkbenchFixture';
        let index = context.characters.findIndex(x => x.name === name);
        if (index < 0) {
            const body = new FormData();
            body.set('ch_name', name);
            body.set('description', '仅用于隔离技术验证的角色。');
            body.set('first_mes', '技术验证开始。');
            body.set('creatorcomment', 'Synthetic fixture; no production data.');
            const headers = { ...context.getRequestHeaders() };
            delete headers['Content-Type'];
            const response = await fetch('/api/characters/create', { method: 'POST', headers, body });
            if (!response.ok) throw new Error('Failed to create fixture character: ' + response.status);
            await context.getCharacters();
            index = context.characters.findIndex(x => x.name === name);
        }
        await context.selectCharacterById(index);
        return { name, index };
    });
}

export async function connect(page) {
    await page.evaluate(() => {
        // A loaded fixture profile can asynchronously reapply its provider.
        // Deselect it before changing API fields, exactly as the native UI does.
        jQuery('#connection_profiles').val('').trigger('change');
        jQuery('#main_api').val('openai').trigger('change');
    });
    await page.waitForTimeout(400);
    await page.evaluate(() => jQuery('#chat_completion_source').val('custom').trigger('change'));
    await page.waitForTimeout(200);
    await page.evaluate(url => {
        jQuery('#custom_api_url_text').val(url).trigger('input');
        jQuery('#custom_model_id').val('workbench-fixture').trigger('input');
        SillyTavern.getContext().chatCompletionSettings.stream_openai = true;
        document.querySelector('#api_button_openai').click();
    }, mockApi);
    await page.waitForFunction(() => SillyTavern.getContext().onlineStatus !== 'no_connection', null, { timeout: 30_000 });
}

export async function selectPaper(page, label, value) {
    const trigger = page.getByRole('combobox', { name: label, exact: true });
    const text = await trigger.evaluate((button, value) => [...button.closest('.wb-select').querySelector('select').options].find(o => o.value === value)?.textContent, String(value));
    if (text == null) throw new Error(`Missing option in ${label}`);
    await trigger.click();
    await page.getByRole('listbox', { name: label, exact: true }).getByRole('option', { name: text, exact: true }).click();
}

export async function paperValue(page, label) {
    return page.getByRole('combobox', { name: label, exact: true }).evaluate(button => button.closest('.wb-select').querySelector('select').value);
}

export const save = (name, value) => fs.writeFileSync(path.join(artifacts, name), JSON.stringify(value, null, 2) + '\n');

/** Leaves focus mode through the reading bar's 退出专注 pill (the layout switcher hides in focus since E2). */
export async function exitFocus(page) {
    await page.getByRole('button', { name: '退出专注', exact: true }).click();
}

/** Parses a computed color (rgb()/rgba() or color(srgb …)) into 0–255 channels plus alpha. */
export function parseColor(value) {
    const srgb = value.match(/^color\(srgb ([\d.]+) ([\d.]+) ([\d.]+)(?: \/ ([\d.]+))?\)$/);
    if (srgb) return [...srgb.slice(1, 4).map((x) => Number(x) * 255), srgb[4] == null ? 1 : Number(srgb[4])];
    const rgb = value.match(/^rgba?\(([\d.]+), ([\d.]+), ([\d.]+)(?:, ([\d.]+))?\)$/);
    if (rgb) return [...rgb.slice(1, 4).map(Number), rgb[4] == null ? 1 : Number(rgb[4])];
    throw new Error(`Unparsed color ${value}`);
}

/** True when two computed colors match within `tolerance` per 0–255 channel. */
export function sameColor(actual, expected, tolerance = 2) {
    const a = parseColor(actual), b = parseColor(expected);
    return a.every((x, i) => Math.abs(x - b[i]) <= (i === 3 ? 0.01 : tolerance));
}

/** Shows a right-sidebar panel; the sidebar reopens on the last panel and keeps its tabs folded. */
export async function openPanel(page, name) {
    const tab = page.locator('.wb-panel-tabs').getByRole('button', { name, exact: true });
    if (await tab.getAttribute('aria-pressed') === 'true') return;
    const toggle = page.getByRole('button', { name: '展开资源分类', exact: true });
    if (await toggle.isVisible()) await toggle.click();
    await tab.click();
}

const resourceKinds = { 连接: 'connection', 预设: 'preset', 世界书: 'world', 用户设定: 'persona' };
/** Opens a resource panel the desktop way: its header pill, then the popover's footer link. Accepts "世界书" or "世界书详情". */
export async function openResource(page, label) {
    const kind = resourceKinds[label.replace(/详情$/, '')];
    if (!kind) throw new Error(`Unknown resource ${label}`);
    // An auto-hiding RP top bar is revealed the way a pointer does: from the window's top edge.
    if (await page.evaluate(() => document.body.classList.contains('wb-rp-top-collapsed'))) {
        await page.mouse.move(740, 4);
        await page.waitForFunction(() => !document.body.classList.contains('wb-rp-top-collapsed'));
        await page.mouse.move(740, 35);
        await page.waitForTimeout(250);
    }
    const pill = page.locator(`.wb-pill[aria-controls="wb-choices-${kind}"]`);
    if (await pill.getAttribute('aria-expanded') !== 'true') await pill.click();
    await page.locator(`#wb-choices-${kind} .wb-pill-pop-foot button`).click();
}

/** Opens a settings page: 设置 in the left column, then the page's entry in the workspace nav. */
export async function openSettings(page, name) {
    const workspace = page.getByRole('dialog', { name: '独立设置工作区', exact: true });
    if (!(await workspace.isVisible())) await page.locator('.wb-nav-footer').getByRole('button', { name: '设置', exact: true }).click();
    await workspace.waitFor();
    await workspace.locator('.wb-settings-nav').getByRole('button', { name, exact: true }).click();
}

/** Switches Noval / RP / 原生 through the segmented control and waits until it settles. */
export async function chooseLayout(page, name) {
    const group = page.getByRole('radiogroup', { name: '切换工作台', exact: true });
    // In RP the switcher follows the auto-hidden header; hovering the top edge reveals it.
    if (!(await group.isVisible())) { await page.mouse.move(page.viewportSize().width / 2, 4); await group.waitFor(); }
    await group.getByRole('radio', { name, exact: true }).click();
    await page.waitForFunction(() => !document.querySelector('.wb-layout-controls[aria-busy="true"]'));
}

/** Opens the right panel from its edge arrow, or closes a pinned one from the card's own 关闭右栏 (E2b). */
export async function toggleRight(page) {
    const close = page.locator('.wb-panel-close');
    if (await close.isVisible()) await close.click();
    else await page.locator('.wb-edge-right').click();
}

/**
 * A world book "RP阵容测试" whose entries 张三 (joy, neutral) and 李四 (anger) have faces in
 * characters/RP阵容测试/<entry>/, plus an entry whose title cannot be a folder; the open chat plays it.
 */
export async function seedCast(page) {
    const sprite = file => fs.readFileSync(path.join(root, 'docs/design/rp-desktop/assets', file)).toString('base64');
    await page.evaluate(async ({ a, b }) => {
        const c = SillyTavern.getContext(), headers = c.getRequestHeaders(), plain = { ...headers };
        delete plain['Content-Type'];
        const entries = {
            0: { uid: 0, comment: '张三', key: ['三哥'], content: '猎户。' },
            1: { uid: 1, comment: '李四', key: ['阿四'], content: '药师。' },
            2: { uid: 2, comment: '王五/村长', key: [], content: '标题不能作文件夹名。' },
            3: { uid: 3, comment: '', key: ['山'], content: '无标题。' },
        };
        if (!(await fetch('/api/worldinfo/edit', { method: 'POST', headers, body: JSON.stringify({ name: 'RP阵容测试', data: { entries } }) })).ok) throw new Error('cast book');
        await workbench.host.world.updateWorldInfoList();
        for (const [who, label, data] of [['张三', 'joy', a], ['张三', 'neutral', a], ['李四', 'anger', b]]) {
            const form = new FormData();
            form.set('avatar', new File([Uint8Array.from(atob(data), x => x.charCodeAt(0))], label + '.webp', { type: 'image/webp' }));
            form.set('name', 'RP阵容测试/' + who);
            form.set('label', label);
            if (!(await fetch('/api/sprites/upload', { method: 'POST', headers: plain, body: form })).ok) throw new Error('cast sprite');
        }
        // A run that stopped halfway may have left what the portraits tab uploads, relabels or moves.
        for (const [who, spriteName] of [['李四', 'neutral'], ['李四', 'smile'], ['李四', 'joy'], ['李四郎', 'anger'], ['李四郎', 'neutral'], ['李四郎', 'joy']])
            await fetch('/api/sprites/delete', { method: 'POST', headers, body: JSON.stringify({ name: 'RP阵容测试/' + who, label: spriteName, spriteName }) });
        await workbench.host.cast.save({ book: 'RP阵容测试', entries: ['张三', '李四'] });
    }, { a: sprite('r-character.webp'), b: sprite('r-user-character.webp') });
}

/**
 * A stand-in for the database plug-in (龙血玄黄·数据库) with its API's semantics: sheet_* tables whose
 * column 0 is the row_id, 1-based updateRow/insertRow/deleteRow that refuse locked targets, 0-based
 * lock toggles, and update / fill-start callbacks. `window.__db` holds the tables, locks and calls.
 */
export async function seedDatabase(page) {
    await page.evaluate(() => {
        const tables = {
            mate: { type: 'chatSheets', version: 1 },
            sheet_global: { name: '全局数据', orderNo: 0, sourceData: { note: '当前时间、地点与天气。' }, content: [[null, '时间', '地点', '天气'], ['1', '第三天 · 黄昏', '灯塔下的渔村', '细雨']] },
            sheet_people: { name: '重要人物', orderNo: 1, sourceData: { note: '出场的重要人物与他们的现状。每个人物一行，离场后保留。' }, content: [
                [null, '姓名', '身份', '与主角的关系', '现状'],
                ['1', '林晚', '灯塔看守人的女儿', '旧识，信任渐深', '在灯塔顶层整理父亲留下的航海日志，发现最后一页被撕去，日志里反复出现一个陌生的坐标。'],
                ['2', '沈舟', '邮差', '刚认识', '每天黄昏送信到灯塔，今天迟到了。'],
                ['3', '老周', '渔夫', '欠主角一个人情', '修补渔网，偶尔说起二十年前的那场风暴。'],
            ] },
            sheet_items: { name: '物品', orderNo: 2, content: [[null, '名称', '数量', '说明'], ['1', '黄铜钥匙', '1', '刻着灯塔的标记'], ['2', '旧航海日志', '1', '最后一页缺失']] },
            sheet_options: { name: '选项表', orderNo: 3, content: [[null, '选项一', '选项二'], ['1', '推门进去', '转身离开']] },
        };
        const locks = {}, calls = [], update = [], fill = [];
        const lockOf = key => (locks[key] ??= { rows: [], cols: [], cells: [] });
        const sheet = name => Object.entries(tables).find(([key, t]) => key.startsWith('sheet_') && t.name === name);
        const notify = () => update.forEach(fn => fn(tables, { persisted: true }));
        const blocked = (key, row, cols) => {
            const l = lockOf(key), at = row - 1, t = tables[key];
            if (l.rows.includes(at)) return true;
            return cols.some(name => { const c = t.content[0].indexOf(name) - 1; return l.cols.includes(c) || l.cells.includes(`${at}:${c}`); });
        };
        const toggle = (list, value) => { const i = list.indexOf(value); if (i < 0) list.push(value); else list.splice(i, 1); return true; };
        window.__db = { tables, locks, calls, fill };
        window.AutoCardUpdaterAPI = {
            exportTableAsJson: () => tables,
            registerTableUpdateCallback: fn => { if (!update.includes(fn)) update.push(fn); },
            unregisterTableUpdateCallback: fn => { const i = update.indexOf(fn); if (i > -1) update.splice(i, 1); },
            registerTableFillStartCallback: fn => { if (!fill.includes(fn)) fill.push(fn); },
            getTableLockState: key => structuredClone(lockOf(key)),
            toggleTableRowLock: (key, row) => toggle(lockOf(key).rows, row),
            toggleTableColLock: (key, col) => toggle(lockOf(key).cols, col),
            toggleTableCellLock: (key, row, col) => toggle(lockOf(key).cells, `${row}:${col}`),
            getUpdateConfigParams: () => ({ autoUpdateThreshold: 3, autoUpdateFrequency: 2, updateBatchSize: 2, autoUpdateTokenThreshold: 0 }),
            updateRow: async (name, row, data) => {
                calls.push(['updateRow', name, row, data]);
                const [key, t] = sheet(name) ?? [];
                if (!t || !t.content[row] || blocked(key, row, Object.keys(data))) return false;
                for (const [col, value] of Object.entries(data)) t.content[row][t.content[0].indexOf(col)] = value;
                notify(); return true;
            },
            insertRow: async (name, data) => {
                calls.push(['insertRow', name, data]);
                const [, t] = sheet(name) ?? [];
                if (!t) return -1;
                const id = String(Math.max(0, ...t.content.slice(1).map(r => Number(r[0]) || 0)) + 1);
                t.content.push([id, ...t.content[0].slice(1).map(col => data[col] ?? '')]);
                notify(); return t.content.length - 1;
            },
            deleteRow: async (name, row) => {
                calls.push(['deleteRow', name, row]);
                const [key, t] = sheet(name) ?? [];
                const l = lockOf(key);
                if (!t || row < 1 || !t.content[row] || l.rows.includes(row - 1) || l.cells.some(c => c.startsWith(`${row - 1}:`))) return false;
                t.content.splice(row, 1); notify(); return true;
            },
            triggerUpdate: async () => {
                calls.push(['triggerUpdate']);
                fill.forEach(fn => fn());
                await new Promise(resolve => setTimeout(resolve, 600));
                tables.sheet_global.content[1][3] = '雨停了';
                notify(); return true;
            },
            openSettings: async () => { calls.push(['openSettings']); return true; },
        };
        workbench.host.database.read();
    });
}

/** The text of a field: a textarea's value, or a Markdown editor's document. The editor's view is
 *  reached the way EditorView.findFromDOM does it in the pinned @codemirror/view. */
export const fieldValue = (locator) =>
    locator.evaluate(n => (n instanceof HTMLTextAreaElement || n instanceof HTMLInputElement ? n.value : n.cmTile.root.view.state.doc.toString()));
