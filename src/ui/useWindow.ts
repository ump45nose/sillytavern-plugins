import { useCallback, useLayoutEffect, useState } from "react";

/** Lists at or below this length render every row: windowing only pays off for long lists. */
export const WINDOW_FROM = 120;
const OVERSCAN = 8;

const scrolls = (node: Element) => /auto|scroll/.test(getComputedStyle(node).overflowY);
/** Where row 0 starts on screen: the list's content box, less its own scroll when it is the scroller. */
const rowsTop = (list: HTMLElement) => {
  const style = getComputedStyle(list);
  return (
    list.getBoundingClientRect().top +
    list.clientTop +
    parseFloat(style.paddingTop) -
    (scrolls(list) ? list.scrollTop : 0)
  );
};

/**
 * Fixed-height rows, windowed. Only the rows inside the visible band (the viewport clipped by the list,
 * when it scrolls itself, and by every clipping ancestor) plus OVERSCAN either side render; the caller
 * puts `before` and `after` tall spacers around them so the scroll height stays that of the whole list.
 * Short lists (`count <= WINDOW_FROM`) render whole. `reveal(index)` scrolls just enough to show a row.
 */
export function useWindow<T extends HTMLElement>(count: number, row: number) {
  const [node, ref] = useState<T | null>(null),
    windowed = count > WINDOW_FROM,
    [range, setRange] = useState<[number, number]>([0, Math.min(count, 40)]);
  useLayoutEffect(() => {
    const list = node;
    if (!windowed || !list) return;
    const clips: HTMLElement[] = scrolls(list) ? [list] : [];
    for (let n = list.parentElement; n; n = n.parentElement)
      if (/auto|scroll|hidden|clip/.test(getComputedStyle(n).overflowY)) clips.push(n);
    let frame = 0;
    const update = () => {
      frame = 0;
      let top = 0,
        bottom = innerHeight;
      for (const n of clips) {
        const r = n.getBoundingClientRect();
        top = Math.max(top, r.top);
        bottom = Math.min(bottom, r.bottom);
      }
      const start = rowsTop(list),
        first = Math.min(count, Math.max(0, Math.floor((top - start) / row) - OVERSCAN)),
        last = Math.min(count, Math.max(first, Math.ceil((bottom - start) / row) + OVERSCAN));
      setRange((r) => (r[0] === first && r[1] === last ? r : [first, last]));
    };
    const schedule = () => {
      if (!frame) frame = requestAnimationFrame(update);
    };
    const observer = new ResizeObserver(schedule);
    clips.forEach((n) => {
      observer.observe(n);
      n.addEventListener("scroll", schedule, { passive: true });
    });
    addEventListener("resize", schedule);
    update();
    return () => {
      cancelAnimationFrame(frame);
      observer.disconnect();
      clips.forEach((n) => n.removeEventListener("scroll", schedule));
      removeEventListener("resize", schedule);
    };
  }, [node, windowed, count, row]);
  const reveal = useCallback(
    (index: number) => {
      if (!node || index < 0) return;
      let box: HTMLElement | null = node;
      while (box && !(box.scrollHeight > box.clientHeight && scrolls(box))) box = box.parentElement;
      if (!box) return;
      // A sticky header above the rows is declared as the scroller's scroll-padding-top.
      const view = box.getBoundingClientRect(),
        pad = parseFloat(getComputedStyle(box).scrollPaddingTop) || 0,
        y = rowsTop(node) + index * row - view.top - box.clientTop;
      if (y < pad) box.scrollTop += y - pad;
      else if (y + row > box.clientHeight) box.scrollTop += y + row - box.clientHeight;
    },
    [node, row],
  );
  const [first, last] = windowed ? [Math.min(range[0], count), Math.min(range[1], count)] : [0, count];
  return { ref, first, last, windowed, before: first * row, after: (count - last) * row, reveal };
}
