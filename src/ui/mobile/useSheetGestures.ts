import { useEffect, useLayoutEffect, useRef, type RefObject } from "react";
import { flushSync } from "react-dom";
import type { MobileSheet, MobileState } from "./types";

export function useSheetGestures(
  sheetRef: RefObject<HTMLDivElement | null>,
  headerRef: RefObject<HTMLElement | null>,
  presence: { value: MobileSheet; exiting: boolean },
  latest: RefObject<MobileState>,
  onClose: () => void,
  onSheet: (sheet: MobileSheet) => void,
) {
  const actions = useRef({ onClose, onSheet });
  actions.current = { onClose, onSheet };
  const close = () => actions.current.onClose();
  const setSheet = (sheet: MobileSheet) => actions.current.onSheet(sheet);
  // A sheet follows its handle away from its edge (down for the bottom sheets, up for the session
  // menu that hangs from the top); past a third of its height or on a flick it closes, otherwise it
  // settles back.
  useEffect(() => {
    const node = sheetRef.current;
    if (!node || presence.exiting) return;
    let drag: {
      y: number;
      pointer: number;
      dy: number;
      previous: { y: number; t: number };
      last: { y: number; t: number };
    } | null = null;
    const down = (e: PointerEvent) => {
      if (e.button !== 0 || !(e.target as Element).closest(".wb-mobile-sheet-grip,.wb-mobile-sheet > header"))
        return;
      if ((e.target as Element).closest("button")) return;
      const at = { y: e.clientY, t: e.timeStamp };
      drag = { y: e.clientY, pointer: e.pointerId, dy: 0, previous: at, last: at };
      node.dataset.wbDrag = "";
    };
    const top = node.classList.contains("is-management");
    const move = (e: PointerEvent) => {
      if (!drag || e.pointerId !== drag.pointer) return;
      drag.dy = top ? Math.min(0, e.clientY - drag.y) : Math.max(0, e.clientY - drag.y);
      drag.previous = drag.last;
      drag.last = { y: e.clientY, t: e.timeStamp };
      node.style.setProperty("--wb-sheet-pull", `${drag.dy}px`);
    };
    const up = (e: PointerEvent) => {
      const current = drag;
      drag = null;
      if (!current || e.pointerId !== current.pointer) return;
      const speed =
        ((current.last.y - current.previous.y) / Math.max(1, current.last.t - current.previous.t)) *
        (top ? -1 : 1);
      delete node.dataset.wbDrag;
      if (speed > 0.5 || Math.abs(current.dy) > node.offsetHeight / 3) close();
      else node.style.removeProperty("--wb-sheet-pull");
    };
    node.addEventListener("pointerdown", down);
    node.addEventListener("pointermove", move);
    node.addEventListener("pointerup", up);
    node.addEventListener("pointercancel", up);
    return () => {
      node.removeEventListener("pointerdown", down);
      node.removeEventListener("pointermove", move);
      node.removeEventListener("pointerup", up);
      node.removeEventListener("pointercancel", up);
    };
  }, [presence.value, presence.exiting]);
  useEffect(() => {
    const header = headerRef.current;
    if (!header) return;
    const veil = () => document.querySelector<HTMLElement>(".wb-mobile-sheet-shade");
    let drag: {
      y: number;
      pointer: number;
      dy: number;
      height: number;
      started: boolean;
      previous: { y: number; t: number };
      last: { y: number; t: number };
    } | null = null;
    const move = (e: PointerEvent) => {
      if (!drag || e.pointerId !== drag.pointer) return;
      const dy = e.clientY - drag.y;
      if (!drag.started) {
        if (Math.abs(dy) < 8) return;
        if (dy < 0) return end();
        drag.started = true;
        flushSync(() => setSheet("management"));
        const node = sheetRef.current!;
        node.dataset.wbDrag = "";
        node.style.setProperty("animation", "none");
        veil()?.style.setProperty("animation", "none");
        drag.height = node.offsetHeight;
      }
      drag.dy = Math.min(drag.height, Math.max(0, dy));
      drag.previous = drag.last;
      drag.last = { y: e.clientY, t: e.timeStamp };
      sheetRef.current!.style.setProperty("--wb-sheet-pull", `${drag.dy - drag.height}px`);
      veil()?.style.setProperty("opacity", String(drag.dy / drag.height));
    };
    const up = (e: PointerEvent) => {
      const current = drag;
      end();
      if (!current?.started || e.pointerId !== current.pointer) return;
      dragged = e.timeStamp;
      const node = sheetRef.current!,
        speed = (current.last.y - current.previous.y) / Math.max(1, current.last.t - current.previous.t);
      delete node.dataset.wbDrag;
      if (e.type === "pointerup" && (speed > 0.45 || (speed > -0.45 && current.dy > current.height * 0.35))) {
        node.style.removeProperty("--wb-sheet-pull");
        veil()?.style.setProperty("transition", "opacity 260ms");
        veil()?.style.setProperty("opacity", "1");
      } else close();
    };
    const end = () => {
      drag = null;
      document.removeEventListener("pointermove", move);
      document.removeEventListener("pointerup", up);
      document.removeEventListener("pointercancel", up);
    };
    const down = (e: PointerEvent) => {
      const state = latest.current;
      if (e.button !== 0 || e.pointerType === "mouse") return;
      if ((e.target as Element).closest("button:not(.wb-mobile-title)")) return;
      if (state.sheet || state.left || state.panel || state.editor) return;
      if (document.body.classList.contains("wb-focus")) return;
      const at = { y: e.clientY, t: e.timeStamp };
      drag = { y: e.clientY, pointer: e.pointerId, dy: 0, height: 0, started: false, previous: at, last: at };
      document.addEventListener("pointermove", move);
      document.addEventListener("pointerup", up);
      document.addEventListener("pointercancel", up);
    };
    // A drag that started on RP's title is not also a tap on it.
    let dragged = -Infinity;
    const swallow = (e: MouseEvent) => {
      if (e.timeStamp - dragged < 400) e.stopPropagation();
    };
    header.addEventListener("pointerdown", down);
    header.addEventListener("click", swallow, true);
    return () => {
      end();
      header.removeEventListener("pointerdown", down);
      header.removeEventListener("click", swallow, true);
    };
  }, []);
  // A sheet that was drawn by the finger hands its motion back to the exit animation.
  useLayoutEffect(() => {
    if (!presence.exiting) return;
    sheetRef.current?.style.removeProperty("animation");
    const shade = document.querySelector<HTMLElement>(".wb-mobile-sheet-shade");
    for (const name of ["animation", "opacity", "transition"]) shade?.style.removeProperty(name);
  }, [presence.exiting]);
}
