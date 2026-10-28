import { useEffect, type RefObject } from "react";
import { flushSync } from "react-dom";
import type { Panel } from "../../host/types";
import { interactive, type MobileState } from "./types";

export function useDrawerGestures(
  rp: boolean,
  latest: RefObject<MobileState>,
  toggleLeft: () => void,
  goPanel: (panel: Panel) => void,
  closeDrawers: () => void,
) {
  // Drawers follow the finger. A sideways drag on the reading (RP: the scene around the dialogue box)
  // pulls the outline out from the left or the panel from the right; a drag on an open drawer or its
  // shade pushes it back. On release, a flick or more than 40% shown decides.
  useEffect(() => {
    type Drag = {
      x: number;
      y: number;
      t: number;
      pointer: number;
      target: Element;
      opening: boolean;
      side?: "left" | "right";
      node?: HTMLElement;
      width?: number;
      shown?: number;
      previous: { x: number; t: number };
      last: { x: number; t: number };
    };
    let drag: Drag | null = null;
    // Drag state lives in data attributes and inline styles on the drawer and its shade only: class
    // writes wake SillyTavern's keyboard observer, and anything on <body> restyles the whole page.
    const shade = () => document.querySelector<HTMLElement>(".wb-mobile-shade");
    const release = (node?: HTMLElement) => {
      if (!node) return;
      delete node.dataset.wbDrag;
      node.style.removeProperty("--wb-drawer-x");
      const veil = shade();
      if (veil) {
        delete veil.dataset.wbDrag;
        veil.style.removeProperty("opacity");
      }
    };
    const down = (e: PointerEvent) => {
      if (e.button !== 0 || e.pointerType !== "touch") return;
      const target = e.target as Element,
        state = latest.current;
      if (state.editor || state.sheet) return;
      const open = state.left || !!state.panel;
      if (open) {
        if (!target.closest(".wb-left,.wb-right,.wb-mobile-shade")) return;
        if (
          target.closest(
            "input,textarea,select,[contenteditable=true],.wb-panel-tabs,.wb-mobile-resource-popup",
          )
        )
          return;
      } else {
        // Selecting text in the reading is not a swipe.
        const selection = getSelection(),
          anchor = selection?.anchorNode,
          inReading = (anchor instanceof Element ? anchor : anchor?.parentElement)?.closest("#chat");
        if (target.closest(interactive) || (selection?.toString() && inReading)) return;
        if (rp ? target.closest(".wb-ui,#sheld,.wb-mobile-header") : !target.closest("#chat")) return;
      }
      const at = { x: e.clientX, t: e.timeStamp };
      drag = {
        x: e.clientX,
        y: e.clientY,
        t: e.timeStamp,
        pointer: e.pointerId,
        target,
        opening: !open,
        side: open ? (state.left ? "left" : "right") : undefined,
        previous: at,
        last: at,
      };
    };
    const move = (e: PointerEvent) => {
      if (!drag || e.pointerId !== drag.pointer) return;
      const dx = e.clientX - drag.x,
        dy = e.clientY - drag.y;
      if (!drag.node) {
        if (Math.hypot(dx, dy) < 10) return;
        if (Math.abs(dx) < Math.abs(dy) * 1.2) {
          drag = null;
          return;
        }
        drag.side ??= dx > 0 ? "left" : "right";
        drag.node = document.querySelector<HTMLElement>(drag.side === "left" ? ".wb-left" : ".wb-right")!;
        drag.width = drag.node.offsetWidth;
        drag.node.dataset.wbDrag = "";
        const veil = shade();
        if (veil) veil.dataset.wbDrag = "";
      }
      const toward = drag.side === "left" ? dx : -dx,
        shown = Math.min(drag.width!, Math.max(0, drag.opening ? toward : drag.width! + toward));
      drag.shown = shown;
      drag.previous = drag.last;
      drag.last = { x: e.clientX, t: e.timeStamp };
      drag.node.style.setProperty("--wb-drawer-x", `${shown}px`);
      shade()?.style.setProperty("opacity", String(shown / drag.width!));
    };
    const up = (e: PointerEvent) => {
      const current = drag;
      drag = null;
      if (!current?.node || e.pointerId !== current.pointer) return;
      const sign = current.side === "left" ? 1 : -1,
        speed =
          ((current.last.x - current.previous.x) * sign) / Math.max(1, current.last.t - current.previous.t),
        travel = (e.clientX - current.x) * sign,
        quick = e.timeStamp - current.t < 300 && Math.abs(travel) > 40,
        flick = speed > 0.35 ? true : speed < -0.35 ? false : quick ? travel > 0 : null,
        open = flick ?? current.shown! > current.width! * 0.4;
      // The new state and the drag styles leave in one frame, so the slide continues from the finger.
      flushSync(() => {
        if (open && current.opening) current.side === "left" ? toggleLeft() : goPanel("character");
        if (!open && !current.opening) closeDrawers();
      });
      release(current.node);
      // A drag that began on a row or the shade must not also click it.
      const swallow = (click: Event) => {
        document.removeEventListener("click", swallow, true);
        if (!current.target.contains(click.target as Node)) return;
        click.stopPropagation();
        click.preventDefault();
      };
      document.addEventListener("click", swallow, true);
      setTimeout(() => document.removeEventListener("click", swallow, true), 300);
    };
    const cancel = () => {
      release(drag?.node);
      drag = null;
    };
    document.addEventListener("pointerdown", down);
    document.addEventListener("pointermove", move);
    document.addEventListener("pointerup", up);
    document.addEventListener("pointercancel", cancel);
    return () => {
      cancel();
      document.removeEventListener("pointerdown", down);
      document.removeEventListener("pointermove", move);
      document.removeEventListener("pointerup", up);
      document.removeEventListener("pointercancel", cancel);
    };
  }, [rp, toggleLeft, goPanel, closeDrawers]);
}
