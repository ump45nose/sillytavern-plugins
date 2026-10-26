/**
 * 抽屉动画 transform 化
 * 来源：cocktail modules/ui-animation-optimizer.js — https://github.com/Lianues/cocktail （作者 Limerence）
 *
 * 1.19.0 的 inline-drawer（public/script.js `.inline-drawer-toggle` 点击处理）用 jQuery slideToggle
 * 逐帧改 height，内容重的抽屉（世界书条目、预设参数）每帧都要重排。这里只替换作用在
 * `.inline-drawer-content` 上的 slideToggle：显示时一次布局到位，再用 Web Animations 播放
 * opacity/transform；收起时淡出后 display:none。其他元素的 slideToggle 走原生实现。
 * 不留任何 CSS 类；减少动效（$.fx.off 或系统偏好）时直接切换。
 */
const SHOW_MS = 160, HIDE_MS = 120;
const SELECTOR = '.inline-drawer-content';

/** jQuery accepts (options), (duration, easing, complete) and their shorter forms; only `complete` matters here. */
function completeOf(args) {
    for (const arg of args) {
        if (typeof arg === 'function') return arg;
        if (arg && typeof arg === 'object' && typeof arg.complete === 'function') return arg.complete;
    }
    return null;
}

export default {
    id: 'drawerAnimation',
    title: '抽屉动画：展开/收起不逐帧重排',
    async probe() {
        const $ = globalThis.jQuery;
        if (typeof $?.fn?.slideToggle !== 'function') return '找不到 jQuery.fn.slideToggle';
        if (typeof Element.prototype.animate !== 'function') return '浏览器不支持 Web Animations';
        return null;
    },
    install() {
        const $ = globalThis.jQuery, original = $.fn.slideToggle;
        /** Element → its running animation and the state it is heading to. */
        const running = new WeakMap();
        const instant = () => $.fx.off || matchMedia('(prefers-reduced-motion: reduce)').matches;
        const toggle = (el, complete) => {
            const current = running.get(el);
            // Mid-animation the target state counts, so a quick second click reverses it.
            const opening = current ? !current.open : getComputedStyle(el).display === 'none';
            current?.animation.cancel();
            running.delete(el);
            const done = () => complete?.call(el);
            if (opening) el.style.display = 'block';
            if (instant()) {
                if (!opening) el.style.display = 'none';
                return done();
            }
            const animation = el.animate(
                opening
                    ? [{ opacity: 0, transform: 'translateY(-6px)' }, { opacity: 1, transform: 'none' }]
                    : [{ opacity: 1, transform: 'none' }, { opacity: 0, transform: 'translateY(-6px)' }],
                { duration: opening ? SHOW_MS : HIDE_MS, easing: 'ease-out' },
            );
            running.set(el, { animation, open: opening });
            animation.onfinish = () => {
                running.delete(el);
                if (!opening) el.style.display = 'none';
                done();
            };
        };
        function slideToggle(...args) {
            const elements = this.toArray();
            if (!elements.length || !elements.every(el => el instanceof HTMLElement && el.matches(SELECTOR)))
                return original.apply(this, args);
            const complete = completeOf(args);
            for (const el of elements) toggle(el, complete);
            return this;
        }
        $.fn.slideToggle = slideToggle;
        return () => {
            if ($.fn.slideToggle === slideToggle) $.fn.slideToggle = original;
        };
    },
};
