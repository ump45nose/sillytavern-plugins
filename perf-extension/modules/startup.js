/**
 * 启动预取 + 提前解遮罩
 * 来源：cocktail modules/startup-optimizer.js — https://github.com/Lianues/cocktail （作者 Limerence）
 *
 * 扩展在 1.19.0 的 getSettings → loadExtensionSettings → activateExtensions 期间就已加载，早于
 * getUserAvatars / getCharacters / getBackgrounds（public/script.js firstLoadInit）。这里在加载时并行发出
 * 这三个请求，原生调用到来时直接复用响应；APP_READY 后丢弃快照，此前任何改动角色/背景的请求都会让对应快照失效。
 *
 * 提前解遮罩：1.19.0 的启动遮罩是 loader.show({ slug: 'app-init' })，ctx.hideLoader() 只关旧式遮罩，
 * 对它无效，所以这里直接隐藏 app-init 句柄（原生随后再 hide 一次是空操作）。工作台在 APP_READY 才挂载，
 * 提前解遮罩会露出半初始化、可点击的原生界面再被工作台替换，因此只在工作台不挂载时（未加载或用户选了原生界面）才提前。
 */
import { addFetchHandler, ctx, requestUrl } from '../core.js';

const PREFETCH = {
    '/api/avatars/get': { omitContentType: true },
    '/api/characters/all': { body: '{}' },
    '/api/backgrounds/all': { body: '{}' },
};
/** A request under these prefixes may change what the snapshot holds. */
const INVALIDATES = { '/api/characters/': ['/api/characters/all', '/api/avatars/get'], '/api/avatars/': ['/api/avatars/get'], '/api/backgrounds/': ['/api/backgrounds/all'] };

/**
 * The workbench mounts at APP_READY unless it is missing or the user chose the native UI. At SETTINGS_LOADED its
 * bundle may still be importing (window.workbench not set yet), but its loader has already run captureStartup.
 */
const workbenchWillMount = () => !!(globalThis.workbench || globalThis.workbenchStartup) && ctx().accountStorage?.getItem('wb-native') !== 'true';

export default {
    id: 'startup',
    title: '启动加速：预取角色 / 头像 / 背景列表（下次加载生效）',
    async probe() {
        const c = ctx();
        if (typeof c.getRequestHeaders !== 'function') return '找不到 getRequestHeaders';
        if (typeof c.loader?.active !== 'function') return '找不到 loader.active';
        return null;
    },
    install() {
        const c = ctx();
        // APP_READY is an auto-fire event in 1.19.0: once emitted it is remembered. Switched on after
        // startup, the module has nothing to speed up until the next load.
        if (c.eventSource.autoFireLastArgs?.has(c.eventTypes.APP_READY)) return () => {};
        const snapshots = new Map();
        for (const [path, { omitContentType, body }] of Object.entries(PREFETCH)) {
            const init = { method: 'POST', headers: c.getRequestHeaders(omitContentType ? { omitContentType } : undefined), body };
            // A failed or non-OK prefetch is never served; the native call goes to the network.
            snapshots.set(path, fetch(path, init).then(async r => (r.ok ? { status: r.status, headers: [...r.headers], text: await r.text() } : null)).catch(() => null));
        }
        let removeHandler = addFetchHandler(async (input, init, next) => {
            const url = requestUrl(input);
            if (!url || url.origin !== location.origin) return next(input, init);
            const snapshot = snapshots.get(url.pathname);
            if (snapshot) {
                // Served once; a second call (e.g. a refresh during startup) goes to the network.
                snapshots.delete(url.pathname);
                const hit = await snapshot;
                return hit ? new Response(hit.text, { status: hit.status, headers: hit.headers }) : next(input, init);
            }
            for (const [prefix, paths] of Object.entries(INVALIDATES))
                if (url.pathname.startsWith(prefix)) paths.forEach(p => snapshots.delete(p));
            return next(input, init);
        });
        const onSettings = () => {
            if (workbenchWillMount()) return;
            const splash = c.loader.active().find(handle => handle.slug === 'app-init');
            void splash?.hide();
        };
        const onReady = () => {
            snapshots.clear();
            removeHandler();
            removeHandler = () => {};
        };
        c.eventSource.once(c.eventTypes.SETTINGS_LOADED, onSettings);
        c.eventSource.once(c.eventTypes.APP_READY, onReady);
        return () => {
            c.eventSource.removeListener(c.eventTypes.SETTINGS_LOADED, onSettings);
            c.eventSource.removeListener(c.eventTypes.APP_READY, onReady);
            onReady();
        };
    },
};
