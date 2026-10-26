// Workbench Perf: six independent performance modules absorbed from cocktail (by Limerence) and
// ST-BaiBai-Tools (by 柏柏); each module file names its source. Settings live in extension_settings.wbPerf.
import { TAG, ctx, moduleEnabled, saveSettings, settings } from './core.js';
import { versionProblem } from './lib/version.js';
import presetDryRun from './modules/preset-dry-run.js';
import regexRefresh from './modules/regex-refresh.js';
import drawerAnimation from './modules/drawer-animation.js';
import worldinfoDrag from './modules/worldinfo-drag.js';
import startup from './modules/startup.js';
import saveGzip from './modules/save-gzip.js';

// Startup first: its prefetch only helps if it leaves before the native calls do.
const MODULES = [startup, saveGzip, presetDryRun, regexRefresh, drawerAnimation, worldinfoDrag];

/** id → { problem: string|null, uninstall: (() => void)|null } */
const state = new Map(MODULES.map(m => [m.id, { problem: null, uninstall: null }]));

function apply(module) {
    const s = state.get(module.id);
    if (s.problem) return;
    const want = moduleEnabled(module.id);
    try {
        if (want && !s.uninstall) s.uninstall = module.install();
        else if (!want && s.uninstall) {
            s.uninstall();
            s.uninstall = null;
        }
    } catch (error) {
        // One broken module never blocks the others.
        s.problem = '启用失败：' + (error?.message ?? error);
        s.uninstall = null;
        console.warn(TAG, module.id, s.problem, error);
    }
}

async function boot() {
    const problem = versionProblem((await import('/script.js')).displayVersion);
    await Promise.all(MODULES.map(async module => {
        const s = state.get(module.id);
        try {
            s.problem = problem ?? (await module.probe());
        } catch (error) {
            s.problem = '探测失败：' + (error?.message ?? error);
        }
        if (s.problem) console.warn(TAG, `${module.id} 已停用：${s.problem}`);
    }));
    for (const module of MODULES) apply(module);
}

function renderPanel() {
    const host = document.getElementById('extensions_settings2');
    if (!host || document.getElementById('wb-perf-settings')) return;
    const root = document.createElement('div');
    root.id = 'wb-perf-settings';
    root.className = 'inline-drawer';
    root.innerHTML = `
        <div class="inline-drawer-toggle inline-drawer-header"><b>Workbench 性能优化</b><div class="inline-drawer-icon fa-solid fa-circle-chevron-down down"></div></div>
        <div class="inline-drawer-content">
            <label class="checkbox_label"><input type="checkbox" data-master> 启用性能优化</label>
            <div class="wb-perf-modules"></div>
        </div>`;
    const master = root.querySelector('[data-master]'), list = root.querySelector('.wb-perf-modules');
    for (const module of MODULES) {
        const row = document.createElement('label');
        row.className = 'checkbox_label';
        row.innerHTML = '<input type="checkbox"><span></span><small class="wb-perf-problem"></small>';
        row.querySelector('input').dataset.module = module.id;
        row.querySelector('span').textContent = module.title;
        list.append(row);
    }
    const sync = () => {
        const s = settings();
        master.checked = s.enabled;
        for (const input of list.querySelectorAll('input')) {
            const { problem } = state.get(input.dataset.module);
            input.checked = s.modules[input.dataset.module] !== false;
            input.disabled = !s.enabled || !!problem;
            input.parentElement.querySelector('.wb-perf-problem').textContent = problem ? `（不可用：${problem}）` : '';
        }
    };
    root.addEventListener('change', event => {
        const input = event.target;
        if (input === master) saveSettings({ enabled: input.checked });
        else if (input.dataset.module) saveSettings({ modules: { [input.dataset.module]: input.checked } });
        MODULES.forEach(apply);
        sync();
    });
    sync();
    host.append(root);
}

await boot();
/** Read-only status for diagnostics and verify:perf: id → { active, problem }. */
globalThis.wbPerf = {
    status: () => Object.fromEntries([...state].map(([id, s]) => [id, { active: !!s.uninstall, problem: s.problem }])),
};
const c = ctx();
// APP_READY auto-fires for late listeners, so this also works when the extension loads after startup.
c.eventSource.on(c.eventTypes.APP_READY, renderPanel);
