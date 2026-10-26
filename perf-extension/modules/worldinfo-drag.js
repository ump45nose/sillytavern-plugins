/**
 * 世界书指示线拖拽
 * 来源：cocktail modules/worldinfo-drag-optimizer.js — https://github.com/Lianues/cocktail （作者 Limerence）
 *
 * 1.19.0 世界书条目列表（public/scripts/world-info.js `worldEntriesList.sortable`）拖拽时 jQuery UI
 * 每次移动都重排整列重条目。这里在拖动手柄按下时接管：拖拽期间只移动一个轻量影子和一条指示线，
 * 松手时一次性把条目移到位，再调用原生 sortable 的 stop 回调写 displayIndex 并保存——保存逻辑仍是原生的。
 */
import { stopEvent } from '../core.js';

const LIST = 'world_popup_entries_list';
const EDGE_PX = 64, MAX_SCROLL_PX = 20;

const titleOf = entry =>
    entry.querySelector('textarea[name="comment"]')?.value.trim() || `UID ${entry.dataset.uid ?? entry.getAttribute('uid') ?? ''}`;

function scrollParent(el) {
    for (let node = el.parentElement; node; node = node.parentElement) {
        const overflow = getComputedStyle(node).overflowY;
        if ((overflow === 'auto' || overflow === 'scroll') && node.scrollHeight > node.clientHeight) return node;
    }
    return document.scrollingElement;
}

export default {
    id: 'worldinfoDrag',
    title: '世界书拖拽排序：拖动时只移动指示线',
    async probe() {
        return typeof globalThis.jQuery?.fn?.sortable === 'function' ? null : '找不到 jQuery UI sortable';
    },
    install() {
        const $ = globalThis.jQuery;
        let drag = null;
        const sortableOf = list => {
            try {
                return $(list).sortable('instance') ? $(list) : null;
            } catch {
                return null;
            }
        };
        const place = () => {
            const { list, entry, indicator, x, y } = drag;
            const hit = document.elementFromPoint(x, y)?.closest('.world_entry');
            const candidates = [...list.querySelectorAll(':scope > .world_entry')].filter(e => e !== entry);
            let target = hit && hit !== entry && hit.parentElement === list ? hit : null, before = true;
            if (target) {
                const r = target.getBoundingClientRect();
                before = y < r.top + r.height / 2;
            } else if (candidates.length) {
                // Off any entry: clamp to the nearer end, or keep the last target inside the list.
                const first = candidates[0].getBoundingClientRect(), last = candidates.at(-1).getBoundingClientRect();
                if (y <= first.top) target = candidates[0];
                else if (y >= last.bottom) (target = candidates.at(-1)), (before = false);
                else if (drag.target?.isConnected) ({ target, before } = drag);
            }
            drag.target = target;
            drag.before = before;
            const listRect = list.getBoundingClientRect();
            const top = target ? target.getBoundingClientRect()[before ? 'top' : 'bottom'] : listRect.top;
            indicator.style.cssText = `left:${listRect.left}px;width:${listRect.width}px;top:${Math.round(top) - 1}px`;
        };
        const frame = () => {
            if (!drag) return;
            const { scroller, ghost, x, y, dx, dy } = drag;
            const r = scroller === document.scrollingElement ? { top: 0, bottom: innerHeight } : scroller.getBoundingClientRect();
            const speed = y < r.top + EDGE_PX ? -(r.top + EDGE_PX - y) : y > r.bottom - EDGE_PX ? y - (r.bottom - EDGE_PX) : 0;
            if (speed) scroller.scrollTop += Math.max(-MAX_SCROLL_PX, Math.min(MAX_SCROLL_PX, speed / 3));
            ghost.style.transform = `translate3d(${Math.round(x - dx)}px,${Math.round(y - dy)}px,0)`;
            place();
            drag.raf = requestAnimationFrame(frame);
        };
        const onMove = event => {
            drag.x = event.clientX;
            drag.y = event.clientY;
        };
        const end = commit => {
            const d = drag;
            drag = null;
            cancelAnimationFrame(d.raf);
            d.ghost.remove();
            d.indicator.remove();
            removeEventListener('pointermove', onMove, true);
            removeEventListener('pointerup', onUp, true);
            removeEventListener('pointercancel', onCancel, true);
            if (!commit || !d.target) return;
            d.list.insertBefore(d.entry, d.before ? d.target : d.target.nextSibling);
            // The native stop callback reads the DOM order, writes displayIndex and saves the book.
            const stop = d.$list.sortable('option', 'stop');
            if (typeof stop === 'function') Promise.resolve(stop.call(d.list, null, { item: $(d.entry) })).catch(error => console.error('[wb-perf] world info reorder save failed', error));
        };
        const onUp = event => {
            onMove(event);
            place();
            end(true);
        };
        const onCancel = () => end(false);
        const onDown = event => {
            if (drag) return stopEvent(event);
            if (event.type === 'pointerdown' && event.button !== 0) return;
            const handle = event.target.closest?.('.drag-handle');
            const entry = handle?.closest('.world_entry');
            const list = entry?.parentElement;
            if (list?.id !== LIST) return;
            const $list = sortableOf(list);
            if (!$list) return;
            stopEvent(event);
            const rect = entry.getBoundingClientRect();
            const ghost = Object.assign(document.createElement('div'), { className: 'wb-perf-drag-ghost', textContent: titleOf(entry) });
            ghost.style.width = rect.width + 'px';
            const indicator = Object.assign(document.createElement('div'), { className: 'wb-perf-drop-line' });
            document.body.append(ghost, indicator);
            drag = { list, $list, entry, ghost, indicator, scroller: scrollParent(list), x: event.clientX, y: event.clientY, dx: event.clientX - rect.left, dy: event.clientY - rect.top, target: null, before: true, raf: 0 };
            addEventListener('pointermove', onMove, true);
            addEventListener('pointerup', onUp, true);
            addEventListener('pointercancel', onCancel, true);
            frame();
        };
        // jQuery UI starts its own drag from mousedown/touchstart; once ours runs, those never reach it.
        const block = event => {
            if (drag || event.target.closest?.(`#${LIST} .world_entry .drag-handle`)) {
                if (sortableOf(document.getElementById(LIST))) stopEvent(event);
            }
        };
        document.addEventListener('pointerdown', onDown, true);
        document.addEventListener('mousedown', block, true);
        document.addEventListener('touchstart', block, { capture: true, passive: false });
        return () => {
            if (drag) end(false);
            document.removeEventListener('pointerdown', onDown, true);
            document.removeEventListener('mousedown', block, true);
            document.removeEventListener('touchstart', block, { capture: true });
        };
    },
};
