/**
 * 预设 dry-run 后台化
 * 来源：cocktail modules/preset-panel-optimizer.js — https://github.com/Lianues/cocktail （作者 Limerence）
 *
 * PromptManager.render(true) 在 1.19.0（public/scripts/PromptManager.js render）里先 await tryGenerate()
 * 做 dry-run token 计数再画列表，开关条目要等计数结束才变化。这里先 render(false) 立即画 UI，dry-run
 * 防抖、单飞放到后台，完成后再 render(false) 刷新计数。只补 prototype.render；BaiBai 补的
 * makeDraggable / renderPromptManagerListItems / getPromptCollection 都是实例级，互不干涉。
 *
 * 实例的 renderDebounced（CHAT_LOADED / MESSAGE_RECEIVED / 模型切换等走它）在构造时绑定了 render，而
 * openai.js 的 promptManager 在 getSettings → changeMainAPI 里构造，早于扩展加载，绑定的是原生 render。
 * 这里把它换成同样 1 s 防抖、按 pm.render 动态派发的版本，这些路径才会走上面的补丁。BaiBai 切预设时
 * 临时把 renderDebounced 换成空函数、之后还原成它当时读到的那个，与此不冲突。
 */
const DEBOUNCE_MS = 250;

let PromptManager = null, script = null, groups = null, utils = null, openai = null, constants = null;

export default {
    id: 'presetDryRun',
    title: '预设面板：先切换 UI，后台补齐 token 计数',
    async probe() {
        [{ PromptManager }, script, groups, utils, openai, constants] = await Promise.all([
            import('/scripts/PromptManager.js'),
            import('/script.js'),
            import('/scripts/group-chats.js'),
            import('/scripts/utils.js'),
            import('/scripts/openai.js'),
            import('/scripts/constants.js'),
        ]);
        if (typeof PromptManager?.prototype?.render !== 'function') return '找不到 PromptManager.prototype.render';
        if (typeof utils.waitUntilCondition !== 'function' || typeof utils.debounce !== 'function') return '找不到 utils.waitUntilCondition / debounce';
        if (typeof constants.debounce_timeout?.relaxed !== 'number') return '找不到 debounce_timeout.relaxed';
        return null;
    },
    install() {
        const proto = PromptManager.prototype, original = proto.render;
        const state = new WeakMap();
        let active = true;
        const schedule = pm => {
            const s = state.get(pm) ?? { timer: 0, running: false, again: false };
            state.set(pm, s);
            clearTimeout(s.timer);
            s.timer = setTimeout(async () => {
                if (s.running) return void (s.again = true);
                s.running = true;
                try {
                    // The native render waits the same way before its dry-run: never compete with a live generation.
                    await utils.waitUntilCondition(() => !script.is_send_press && !groups.is_group_generating, 1024 * 1024, 100);
                    await pm.tryGenerate();
                } catch (error) {
                    console.debug('[wb-perf] background dry-run failed', error);
                } finally {
                    s.running = false;
                    if (active) original.call(pm, false);
                    if (s.again) {
                        s.again = false;
                        schedule(pm);
                    }
                }
            }, DEBOUNCE_MS);
        };
        function render(afterTryGenerate = true) {
            if (!active || afterTryGenerate !== true) return original.call(this, afterTryGenerate);
            original.call(this, false);
            schedule(this);
        }
        proto.render = render;
        // Built before this extension loaded (see header); an instance built later binds the patched render itself.
        const pm = openai.promptManager, nativeDebounced = pm?.renderDebounced;
        const renderDebounced = pm && utils.debounce(() => pm.render(), constants.debounce_timeout.relaxed);
        if (pm) pm.renderDebounced = renderDebounced;
        return () => {
            active = false;
            if (proto.render === render) proto.render = original;
            if (pm && pm.renderDebounced === renderDebounced) pm.renderDebounced = nativeDebounced;
        };
    },
};
