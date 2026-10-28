import { useEffect, useLayoutEffect, useRef, type RefObject } from "react";
import type { Panel } from "../../host/types";
import { motionAllowed } from "../Motion";

export function useOverlayFocus(
  left: boolean,
  panel: Panel,
  sheet: boolean,
  sheetRef: RefObject<HTMLDivElement | null>,
  onClose: () => void,
  onCloseDrawers: () => void,
) {
  const actions = useRef({ onClose, onCloseDrawers });
  actions.current = { onClose, onCloseDrawers };
  const close = () => actions.current.onClose();
  const closeDrawers = () => actions.current.onCloseDrawers();
  useLayoutEffect(() => {
    const chat = document.getElementById("sheld")!,
      previous = chat.inert;
    chat.inert = left || !!panel || !!sheet;
    return () => {
      chat.inert = previous;
    };
  }, [left, panel, sheet]);
  useLayoutEffect(() => {
    const target = left
      ? document.querySelector<HTMLElement>(".wb-left")
      : panel
        ? document.querySelector<HTMLElement>(".wb-right")
        : sheet
          ? sheetRef.current
          : null;
    if (!target) return;
    const previous = document.activeElement as HTMLElement,
      frame = requestAnimationFrame(() => {
        const close = document.querySelector<HTMLElement>(
          left ? ".wb-mobile-drawer-close" : ".wb-panel-close",
        );
        (sheet ? sheetRef.current?.querySelector<HTMLElement>("button") : close)?.focus({
          preventScroll: true,
        });
      });
    const nestedOverlay = () =>
      document.activeElement?.closest("dialog[open],.wb-mobile-resource-popup,.wb-resource-menu,.wb-popover");
    const key = (e: KeyboardEvent) => {
      if (e.key !== "Escape" || nestedOverlay()) return;
      // CodeMirror uses Escape followed by Tab to leave its list-indentation keymap.
      if (document.activeElement?.closest(".cm-content")) return;
      e.preventDefault();
      e.stopImmediatePropagation();
      sheet ? close() : closeDrawers();
    };
    const tab = (e: KeyboardEvent) => {
      // Run after the editor's keymap, so a handled Tab can still indent a list.
      if (e.key !== "Tab" || e.defaultPrevented || nestedOverlay()) return;
      const focusable = "button,input:not([type=hidden]),textarea,select,a[href],[tabindex]",
        nodes = [
          ...(sheet ? target : document.body).querySelectorAll<HTMLElement>(
            sheet
              ? focusable
              : `.wb-mobile-drawer-close, :is(.wb-left.is-open,.wb-right.is-open) :is(${focusable})`,
          ),
        ].filter(
          (n) =>
            n.tabIndex >= 0 &&
            !n.matches(":disabled") &&
            !n.closest("[inert],[hidden]") &&
            n.getBoundingClientRect().height > 0,
        );
      const index = nodes.indexOf(document.activeElement as HTMLElement);
      if (!nodes.length) return;
      if (e.shiftKey && index <= 0) {
        e.preventDefault();
        nodes.at(-1)?.focus();
      } else if (!e.shiftKey && (index < 0 || index === nodes.length - 1)) {
        e.preventDefault();
        nodes[0].focus();
      }
    };
    document.addEventListener("keydown", key, true);
    document.addEventListener("keydown", tab);
    return () => {
      cancelAnimationFrame(frame);
      document.removeEventListener("keydown", key, true);
      document.removeEventListener("keydown", tab);
      if (previous?.isConnected && previous.tagName !== "TEXTAREA") previous.focus({ preventScroll: true });
    };
  }, [left, panel, !!sheet]);
  // The panel's tab row scrolls; keep the open tab in view.
  useEffect(() => {
    if (!panel) return;
    const frame = requestAnimationFrame(() => {
      const tab = document.querySelector<HTMLElement>(".wb-right .wb-panel-tab.is-active"),
        row = tab?.parentElement;
      row?.scrollTo({
        left: tab!.offsetLeft - row.offsetLeft - (row.clientWidth - tab!.offsetWidth) / 2,
        behavior: motionAllowed() ? "smooth" : "auto",
      });
    });
    return () => cancelAnimationFrame(frame);
  }, [panel]);
}
