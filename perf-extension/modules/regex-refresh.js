/**
 * 正则面板免重刷
 * 来源：cocktail modules/regex-refresh-optimizer.js — https://github.com/Lianues/cocktail （作者 Limerence）
 *
 * 1.19.0 内置正则扩展（public/scripts/extensions/regex/index.js）每次开关脚本都 reloadCurrentChat()
 * 整聊重渲染：单条开关（saveRegexScript）、批量启用/停用（bulkToggleRegexScripts）、角色/预设正则
 * 授权开关。面板可见期间这里在捕获阶段接管这几种开关：写同样的数据、同样的保存路径，只更新复选框，
 * 记下"待刷新"；面板收起（不可见）时统一 reloadCurrentChat 一次。删除、移动、排序、正则预设保持原生。
 * 生成提示词时正则直接读设置，不受影响；待刷新只关乎已显示的楼层。
 */
import { ctx, stopEvent } from '../core.js';

const LISTS = '#saved_regex_scripts, #saved_scoped_scripts, #saved_preset_scripts';
const CHECK_MS = 400;

let engine = null;

const panel = () => document.querySelector('.regex_settings .inline-drawer-content');
const visible = el => !!el && el.getClientRects().length > 0;

function findScript(id) {
    for (const type of Object.values(engine.SCRIPT_TYPES)) {
        const script = engine.getScriptsByType(type).find(s => s.id === id);
        if (script) return { script, type };
    }
    return null;
}

/**
 * The same writes saveRegexScript (single toggle, which also grants the scoped/preset permission) and
 * bulkToggleRegexScripts make, minus loadRegexScripts and reloadCurrentChat.
 */
async function saveTypes(types, { grant }) {
    const c = ctx(), { SCOPED, PRESET } = engine.SCRIPT_TYPES;
    for (const type of types) {
        await engine.saveScriptsByType(engine.getScriptsByType(type), type);
        if (grant && type === SCOPED) engine.allowScopedScripts(c.characters[c.characterId]);
        if (grant && type === PRESET) engine.allowPresetScripts(engine.getCurrentPresetAPI(), engine.getCurrentPresetName());
    }
    c.saveSettingsDebounced();
}

const reportSaveError = error => {
    console.error('[wb-perf] regex save failed', error);
    globalThis.toastr?.error(String(error?.message ?? error), '正则保存失败');
};

export default {
    id: 'regexRefresh',
    title: '正则面板：开关脚本不整聊重渲染，收起面板时统一刷新',
    async probe() {
        engine = await import('/scripts/extensions/regex/engine.js');
        const needed = ['getScriptsByType', 'saveScriptsByType', 'allowScopedScripts', 'disallowScopedScripts', 'allowPresetScripts', 'disallowPresetScripts', 'getCurrentPresetAPI', 'getCurrentPresetName'];
        const missing = needed.filter(name => typeof engine[name] !== 'function');
        if (missing.length || !engine.SCRIPT_TYPES) return '正则引擎缺少 ' + (missing.join('、') || 'SCRIPT_TYPES');
        if (typeof ctx().reloadCurrentChat !== 'function') return '找不到 reloadCurrentChat';
        return null;
    },
    install() {
        let dirty = false, timer = 0;
        const markDirty = () => {
            dirty = true;
            timer ||= setInterval(check, CHECK_MS);
        };
        const clear = () => {
            dirty = false;
            clearInterval(timer);
            timer = 0;
        };
        // Polls only while a refresh is owed, and stops as soon as it is paid.
        const check = () => {
            if (!dirty || visible(panel())) return;
            clear();
            if (ctx().getCurrentChatId()) void ctx().reloadCurrentChat();
        };
        const toggleOne = (label, disabled) => {
            const found = findScript(label.id);
            if (!found) return false;
            found.script.disabled = disabled;
            label.querySelector('.disable_regex').checked = disabled;
            void saveTypes(new Set([found.type]), { grant: true }).catch(reportSaveError);
            markDirty();
            return true;
        };
        const onClick = event => {
            if (!visible(panel())) return;
            const target = event.target;
            const icon = target.closest?.('.regex-toggle-on, .regex-toggle-off');
            const label = icon?.closest('.regex-script-label');
            if (label?.closest(LISTS)) {
                // Native semantics: the "on" icon shows on an enabled script and disables it.
                if (toggleOne(label, icon.classList.contains('regex-toggle-on'))) stopEvent(event);
                return;
            }
            const bulk = target.closest?.('#bulk_enable_regex, #bulk_disable_regex');
            if (!bulk) return;
            const enable = bulk.id === 'bulk_enable_regex';
            const labels = [...document.querySelectorAll(`#regex_container .regex-script-label`)]
                .filter(l => l.querySelector('.regex_bulk_checkbox')?.checked);
            const changes = labels.map(l => ({ label: l, found: findScript(l.id) }))
                .filter(x => x.found && !!x.found.script.disabled === enable);
            // Nothing to change: the native handler shows its own warning.
            if (!changes.length) return;
            stopEvent(event);
            const types = new Set();
            for (const { label, found } of changes) {
                found.script.disabled = !enable;
                label.querySelector('.disable_regex').checked = !enable;
                types.add(found.type);
            }
            void saveTypes(types, { grant: false }).catch(reportSaveError);
            markDirty();
        };
        const onInput = event => {
            const target = event.target;
            if (!(target instanceof HTMLInputElement) || !visible(panel())) return;
            const label = target.closest('.regex-script-label');
            if (target.classList.contains('disable_regex') && label?.closest(LISTS)) {
                if (toggleOne(label, target.checked)) stopEvent(event);
                return;
            }
            if (target.id !== 'regex_scoped_toggle' && target.id !== 'regex_preset_toggle') return;
            const c = ctx();
            if (target.id === 'regex_scoped_toggle') {
                // No character or a group chat: leave it to the native handler and its error toast.
                if (c.characterId === undefined || c.groupId) return;
                const character = c.characters[c.characterId];
                target.checked ? engine.allowScopedScripts(character) : engine.disallowScopedScripts(character);
            } else {
                const api = engine.getCurrentPresetAPI(), name = engine.getCurrentPresetName();
                target.checked ? engine.allowPresetScripts(api, name) : engine.disallowPresetScripts(api, name);
            }
            stopEvent(event);
            c.saveSettingsDebounced();
            markDirty();
        };
        const c = ctx(), changed = c.eventTypes.CHAT_CHANGED;
        // A chat switch renders with the current scripts anyway.
        c.eventSource.on(changed, clear);
        document.addEventListener('click', onClick, true);
        document.addEventListener('input', onInput, true);
        return () => {
            document.removeEventListener('click', onClick, true);
            document.removeEventListener('input', onInput, true);
            c.eventSource.removeListener(changed, clear);
            const owed = dirty;
            clear();
            if (owed && c.getCurrentChatId()) void c.reloadCurrentChat();
        };
    },
};
